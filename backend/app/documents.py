import codecs
from enum import Enum
import hashlib
import os
from pathlib import Path
import secrets
import shutil
from typing import Annotated
from uuid import UUID, uuid4
import zipfile

import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_UPLOAD_BYTES = int(os.getenv("BROSKI_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
STORAGE_ROOT = Path(os.getenv("BROSKI_STORAGE_ROOT", "data"))
CHUNK_BYTES = 1024 * 1024


class DocumentType(str, Enum):
    book = "book"
    note = "note"
    policy = "policy"
    insurance = "insurance"
    deed = "deed"
    identity = "identity"
    other = "other"


class Document(BaseModel):
    id: UUID
    title: str
    document_type: DocumentType
    original_filename: str
    media_type: str
    size_bytes: int
    sha256: str
    status: str
    created_at: str
    updated_at: str


class ProcessingStatus(BaseModel):
    status: str
    attempts: int
    error: str | None
    review_extracted_text: bool


def connection():
    return psycopg.connect(connect_timeout=3, options="-c statement_timeout=5000", row_factory=dict_row)


def current_owner(authorization: Annotated[str | None, Header()] = None) -> str:
    expected = os.getenv("BROSKI_DEV_TOKEN")
    owner = os.getenv("BROSKI_DEV_OWNER_ID")
    if not expected or not owner:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Document authentication is not configured")
    scheme, separator, supplied = (authorization or "").partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer token", {"WWW-Authenticate": "Bearer"})
    return owner


def clean_filename(filename: str | None) -> tuple[str, str]:
    name = Path((filename or "").replace("\\", "/")).name.strip()
    if not name or name in {".", ".."} or "\x00" in name or len(name) > 255:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid filename")
    return name, Path(name).suffix.lower()


def validate_file(path: Path, suffix: str) -> str:
    with path.open("rb") as source:
        head = source.read(8)
    if suffix == ".pdf" and head.startswith(b"%PDF-"):
        return "application/pdf"
    if suffix == ".png" and head == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if suffix in {".jpg", ".jpeg"} and head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if suffix == ".docx" and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            if "word/document.xml" in archive.namelist():
                return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix in {".txt", ".md"}:
        decoder = codecs.getincrementaldecoder("utf-8")()
        try:
            with path.open("rb") as source:
                while chunk := source.read(CHUNK_BYTES):
                    decoder.decode(chunk)
                decoder.decode(b"", final=True)
            return "text/markdown" if suffix == ".md" else "text/plain"
        except UnicodeDecodeError:
            pass
    raise HTTPException(
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        "File content does not match a supported PDF, DOCX, PNG, JPEG, Markdown, or UTF-8 text file",
    )


def serialize(row: dict) -> Document:
    return Document(**{**row, "created_at": row["created_at"].isoformat(), "updated_at": row["updated_at"].isoformat()})


@router.post("", response_model=Document, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: Annotated[UploadFile, File()],
    document_type: Annotated[DocumentType, Form()],
    owner: Annotated[str, Depends(current_owner)],
    title: Annotated[str | None, Form(max_length=300)] = None,
):
    filename, suffix = clean_filename(file.filename)
    document_id = uuid4()
    incoming = STORAGE_ROOT / ".incoming"
    originals = STORAGE_ROOT / "originals"
    incoming.mkdir(parents=True, exist_ok=True)
    originals.mkdir(parents=True, exist_ok=True)
    temporary = incoming / f"{document_id}.upload"
    destination = originals / f"{document_id}{suffix}"
    size = 0
    digest = hashlib.sha256()
    try:
        with temporary.open("xb") as output:
            while chunk := file.file.read(CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File exceeds upload limit")
                output.write(chunk)
                digest.update(chunk)
        if not size:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is empty")
        media_type = validate_file(temporary, suffix)
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        display_title = (title or Path(filename).stem).strip()
        if not display_title:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Title cannot be empty")
        storage_key = destination.name
        try:
            with connection() as database:
                row = database.execute(
                    """
                    INSERT INTO public.documents
                        (id, owner_id, title, document_type, original_filename, media_type,
                         storage_key, size_bytes, sha256, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued')
                    RETURNING id, title, document_type, original_filename, media_type,
                              size_bytes, sha256, status, created_at, updated_at
                    """,
                    (document_id, owner, display_title, document_type.value, filename, media_type,
                     storage_key, size, digest.hexdigest()),
                ).fetchone()
                database.execute(
                    "INSERT INTO public.ingestion_jobs (document_id, status) VALUES (%s, 'queued')",
                    (document_id,),
                )
        except psycopg.Error:
            destination.unlink(missing_ok=True)
            raise
        return serialize(row)
    finally:
        temporary.unlink(missing_ok=True)
        file.file.close()


@router.get("", response_model=list[Document])
def list_documents(owner: Annotated[str, Depends(current_owner)]):
    with connection() as database:
        rows = database.execute(
            """
            SELECT id, title, document_type, original_filename, media_type,
                   size_bytes, sha256, status, created_at, updated_at
            FROM public.documents
            WHERE owner_id = %s AND deleted_at IS NULL
            ORDER BY created_at DESC
            """,
            (owner,),
        ).fetchall()
    return [serialize(row) for row in rows]


def owned_document(document_id: UUID, owner: str) -> dict:
    with connection() as database:
        row = database.execute(
            """
            SELECT id, title, document_type, original_filename, media_type, storage_key,
                   size_bytes, sha256, status, created_at, updated_at
            FROM public.documents
            WHERE id = %s AND owner_id = %s AND deleted_at IS NULL
            """,
            (document_id, owner),
        ).fetchone()
    if not row:
        # Use one response for absent and unauthorized records to avoid existence disclosure.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return row


@router.get("/{document_id}", response_model=Document)
def get_document(document_id: UUID, owner: Annotated[str, Depends(current_owner)]):
    row = owned_document(document_id, owner)
    row.pop("storage_key")
    return serialize(row)


@router.get("/{document_id}/status", response_model=ProcessingStatus)
def get_processing_status(document_id: UUID, owner: Annotated[str, Depends(current_owner)]):
    document = owned_document(document_id, owner)
    with connection() as database:
        row = database.execute(
            """SELECT d.status, j.attempts, j.error
               FROM public.ingestion_jobs j JOIN public.documents d ON d.id = j.document_id
               WHERE j.document_id = %s""",
            (document_id,),
        ).fetchone()
    return ProcessingStatus(
        **row,
        review_extracted_text=document["media_type"] in {"application/pdf", "image/png", "image/jpeg"},
    )


@router.get("/{document_id}/download")
def download_document(document_id: UUID, owner: Annotated[str, Depends(current_owner)]):
    row = owned_document(document_id, owner)
    path = STORAGE_ROOT / "originals" / row["storage_key"]
    if not path.is_file():
        raise HTTPException(status.HTTP_410_GONE, "Stored document is unavailable")
    return FileResponse(path, media_type=row["media_type"], filename=row["original_filename"])


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: UUID, owner: Annotated[str, Depends(current_owner)]):
    with connection() as database:
        row = database.execute(
            """
            UPDATE public.documents
            SET status = 'deleted', deleted_at = now(), updated_at = now()
            WHERE id = %s AND owner_id = %s AND deleted_at IS NULL
            RETURNING storage_key
            """,
            (document_id, owner),
        ).fetchone()
        if row:
            database.execute(
                "UPDATE public.ingestion_jobs SET status = 'cancelled', lease_token = NULL, updated_at = now() WHERE document_id = %s",
                (document_id,),
            )
            database.execute("DELETE FROM public.document_chunks WHERE document_id = %s", (document_id,))
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    source = STORAGE_ROOT / "originals" / row["storage_key"]
    if source.exists():
        deleted = STORAGE_ROOT / ".deleted"
        deleted.mkdir(parents=True, exist_ok=True)
        shutil.move(source, deleted / row["storage_key"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)
