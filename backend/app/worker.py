"""One durable ingestion worker. Start with: python -m app.worker."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from app.documents import STORAGE_ROOT, connection
from app.embedding import embed_passages, model_version

PARSER_VERSION = "pymupdf-1.28.2-docx-1.2-tesseract-eng-v2"
MAX_ATTEMPTS = 3
PROCESS_TIMEOUT = 300
LEASE_SECONDS = 600
MAX_PAGES = int(os.getenv("BROSKI_MAX_PAGES", "300"))


def queue_stale_embeddings():
    with connection() as database:
        database.execute("""
            WITH stale AS (
                UPDATE public.documents d SET status = 'queued', updated_at = now()
                WHERE d.status = 'ready' AND d.deleted_at IS NULL
                  AND EXISTS (
                    SELECT 1 FROM public.document_chunks c
                    WHERE c.document_id = d.id
                      AND (c.embedding_model IS DISTINCT FROM %s
                           OR c.parser_version IS DISTINCT FROM %s)
                  )
                RETURNING d.id
            )
            INSERT INTO public.ingestion_jobs (document_id, status)
            SELECT id, 'queued' FROM stale
            ON CONFLICT (document_id) DO UPDATE
            SET status = 'queued', attempts = 0, available_at = now(),
                lease_until = NULL, lease_token = NULL, error = NULL, updated_at = now()
        """, (model_version(), PARSER_VERSION))


def claim():
    token = uuid4()
    with connection() as database:
        database.execute("""
            UPDATE public.ingestion_jobs j SET status = 'failed',
                error = 'Processing interrupted too many times', lease_token = NULL, updated_at = now()
            WHERE j.status = 'processing' AND j.lease_until < now() AND j.attempts >= %s
        """, (MAX_ATTEMPTS,))
        row = database.execute("""
            WITH next_job AS (
                SELECT j.document_id FROM public.ingestion_jobs j
                JOIN public.documents d ON d.id = j.document_id
                WHERE d.deleted_at IS NULL AND j.attempts < %s
                  AND ((j.status = 'queued' AND j.available_at <= now())
                    OR (j.status = 'processing' AND j.lease_until < now()))
                ORDER BY j.available_at
                FOR UPDATE OF j SKIP LOCKED LIMIT 1
            )
            UPDATE public.ingestion_jobs j
            SET status = 'processing', attempts = attempts + 1,
                lease_until = now() + (%s * interval '1 second'),
                lease_token = %s, error = NULL, updated_at = now()
            FROM next_job WHERE j.document_id = next_job.document_id
            RETURNING j.document_id, j.attempts
        """, (MAX_ATTEMPTS, LEASE_SECONDS, token)).fetchone()
    with connection() as database:
        database.execute("""
            UPDATE public.documents d SET status = 'failed', updated_at = now()
            FROM public.ingestion_jobs j
            WHERE d.id = j.document_id AND j.status = 'failed' AND d.status = 'processing'
              AND d.deleted_at IS NULL
        """)
    if row:
        with connection() as database:
            database.execute("""
                UPDATE public.documents SET status = 'processing', updated_at = now()
                WHERE id = %s AND deleted_at IS NULL
            """, (row["document_id"],))
    return (row["document_id"], token) if row else None


def finish(document_id, token, chunks=None, vectors=None, error=None):
    with connection() as database:
        document = database.execute("""
            SELECT storage_key, sha256 FROM public.documents
            WHERE id = %s AND deleted_at IS NULL FOR UPDATE
        """, (document_id,)).fetchone()
        if not document:
            return
        job = database.execute("""
            SELECT attempts FROM public.ingestion_jobs
            WHERE document_id = %s AND status = 'processing' AND lease_token = %s FOR UPDATE
        """, (document_id, token)).fetchone()
        if not job:
            return
        if error:
            retry = job["attempts"] < MAX_ATTEMPTS
            database.execute("""
                UPDATE public.ingestion_jobs
                SET status = %s, error = %s,
                    available_at = now() + (%s * interval '1 second'),
                    lease_token = NULL, lease_until = NULL, updated_at = now()
                WHERE document_id = %s
            """, ("queued" if retry else "failed", error,
                  10 * 2 ** (job["attempts"] - 1), document_id))
            database.execute(
                "UPDATE public.documents SET status = %s, updated_at = now() WHERE id = %s",
                ("queued" if retry else "failed", document_id),
            )
            return
        database.execute("DELETE FROM public.document_chunks WHERE document_id = %s", (document_id,))
        for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            database.execute("""
                INSERT INTO public.document_chunks
                    (document_id, ordinal, text, page_number, section_path,
                     source_sha256, parser_version, embedding, embedding_model)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s)
            """, (document_id, ordinal, chunk["text"], chunk["page_number"],
                  chunk["section_path"], document["sha256"], PARSER_VERSION,
                  vector, model_version()))
        database.execute(
            "UPDATE public.documents SET status = 'ready', updated_at = now() WHERE id = %s",
            (document_id,),
        )
        database.execute("""
            UPDATE public.ingestion_jobs SET status = 'complete', error = NULL,
                lease_token = NULL, lease_until = NULL, updated_at = now()
            WHERE document_id = %s
        """, (document_id,))


def process_one():
    claimed = claim()
    if not claimed:
        return False
    document_id, token = claimed
    with connection() as database:
        document = database.execute(
            "SELECT storage_key, sha256, title FROM public.documents WHERE id = %s",
            (document_id,),
        ).fetchone()
    source = STORAGE_ROOT / "originals" / document["storage_key"]
    try:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != document["sha256"]:
            raise ValueError("Original file checksum changed")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "chunks.json"
            subprocess.run(
                [sys.executable, "-m", "app.extract", str(source), str(output), str(MAX_PAGES)],
                check=True, capture_output=True, timeout=PROCESS_TIMEOUT,
            )
            chunks = json.loads(output.read_text(encoding="utf-8"))
        vectors = embed_passages(chunks, document["title"])
        finish(document_id, token, chunks=chunks, vectors=vectors)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        # Do not expose raw parser stderr or source content through the API.
        error = str(exc) if isinstance(exc, ValueError) else "Document processing failed"
        finish(document_id, token, error=error[:200])
    return True


if __name__ == "__main__":
    queue_stale_embeddings()
    while True:
        if not process_one():
            time.sleep(2)
