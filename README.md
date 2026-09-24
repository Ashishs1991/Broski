# Broski

A personal document assistant: retrieve original files and answer from your books, notes, policies, and other documents with citations.

## Current state

**T01–T02 complete; T03 and T04 implemented locally.** Upload, list, detail, private download, delete, and evidence search are owner-scoped. The worker extracts text, creates chunks, and indexes them with a local embedding model before a document becomes ready. Representative OCR accuracy checks remain for T03; chat, production login, and Telegram remain ahead. The bearer token is for loopback development only.

Read [PROJECT_PLAN.md](PROJECT_PLAN.md) for the updated MVP scope, stack, task order, and acceptance criteria.

## Run locally with Docker

Requires Docker Engine/Desktop running with Compose available.

1. Copy `.env.example` to `.env`.
2. Set `PGPASSWORD` and `BROSKI_DEV_TOKEN` in `.env` to unique local secrets. Missing values make Compose reject startup.
3. Run:

```sh
docker compose up --build
```

Open <http://localhost:8000/docs>. Check:

```sh
curl --fail http://localhost:8000/health/live
curl --fail http://localhost:8000/health/ready
```

Liveness returns 200 when the API runs. Readiness returns 200 only when it can connect to PostgreSQL and find the vector extension; otherwise it returns 503 without connection details.

Ports bind to loopback. The database is persisted in a Docker volume. Flyway applies pending migrations before API startup. It records versions/checksums in `flyway_history.flyway_schema_history`. Changing the `.env` password later does not change an existing database user's password. Do not delete persistent volumes to troubleshoot real data without a backup.

## Database migrations with Flyway

SQL migrations live in `infra/migrations/`. V1 enables pgvector, V2 creates the document registry, V3 adds jobs/chunks, and V4 adds 384-dimensional vectors and PostgreSQL full-text search. V4 requeues previously ready documents so the worker fills their vectors before publishing them as ready again.

Startup order is `db healthy → migrate succeeds → api and worker start`. A failed migration prevents new API or worker containers from starting. For an already-running application, apply migrations explicitly as part of each release; Compose does not pause or restart a running API just because a migration file changed.

```sh
# Normal local startup, including migration
docker compose up --build

# Inspect, validate, or apply migrations to the configured local database
docker compose run --rm migrate info
docker compose run --rm migrate validate
docker compose run --rm migrate migrate
```

Name future files `V5__...sql`, `V6__...sql`, and so on. Never edit or rename an applied versioned migration: add a new version. A later deployment should use a dedicated migration identity and a less privileged API identity; local Compose currently uses one development database owner.

Flyway stores its history in the dedicated `flyway_history` schema. This lets it adopt an existing local database where the earlier initialization script already enabled pgvector, without baselining away V1 or recreating the volume. Future application migrations must explicitly qualify their objects, for example `public.documents`, rather than creating them in the history schema. This adoption path covers the known extension-only starter database, not arbitrary preexisting application schemas.

Automatic baselining and `clean` are disabled. Do not use `repair` to hide an unexplained checksum mismatch. Back up persistent data and investigate discrepancies before changing migration history. These migrations install the extension, not its server binaries; the PostgreSQL image must already include pgvector.

To run the database migration integration checks:

```sh
python3 infra/test_migrations.py
```

This creates an isolated, randomly named Docker project without host ports. It tests fresh installation, repeat runs, adoption of the previous extension-only database, and rejection of an altered migration checksum. It removes only its own disposable database volume when finished; it does not operate on the Broski database.

## Run API tests without Docker

From the repository root, using Python 3.11:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd backend
../.venv/bin/python -m pytest -q
```

To run just the API from `backend/`:

```sh
../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --env-file ../.env
```

Readiness will remain 503 until the configured database is running. The tests simulate database success/failure; they are not evidence that a live PostgreSQL instance was tested.

## Development document vault

The current authentication boundary is deliberately local-only. Send the configured token as `Authorization: Bearer ...`; Broski derives the owner from `BROSKI_DEV_OWNER_ID`, never from request data.

```sh
curl -H "Authorization: Bearer $BROSKI_DEV_TOKEN" \
  -F document_type=policy \
  -F title="Sample policy" \
  -F file=@sample-policy.pdf \
  http://127.0.0.1:8000/documents

curl -H "Authorization: Bearer $BROSKI_DEV_TOKEN" \
  http://127.0.0.1:8000/documents

curl -OJ -H "Authorization: Bearer $BROSKI_DEV_TOKEN" \
  http://127.0.0.1:8000/documents/DOCUMENT_ID/download
```

Accepted file contents match PDF, DOCX, PNG, JPEG, Markdown, or UTF-8 plain text. Extensions and client MIME types are not trusted. Files are stored under generated IDs in the gitignored `data/` directory with mode `0600`. The upload limit is 50 MiB.

Uploads return `queued`; poll `GET /documents/DOCUMENT_ID/status` for `processing`, `ready`, or `failed`, including attempt count and a safe failure summary. The worker limits PDFs to 300 pages, extracted text to 2 million characters, and one processing attempt to five minutes. It retries transient failures up to three times; interrupted jobs become available again after a ten-minute lease. Originals are checked against their SHA-256 before processing. Reprocessing replaces chunks transactionally, so a restarted worker does not duplicate active chunks.

`review_extracted_text` is true for PDFs and images because OCR/layout extraction can misread important numbers. Check insurance values against the original before relying on them. The worker uses PyMuPDF for digital PDFs, python-docx for Word, and local English Tesseract for scans. This initial worker processes one job at a time.

## Inspect and search evidence

When a document becomes `ready`, `GET /documents/DOCUMENT_ID/evidence` returns its extracted chunks with page/section, source checksum, parser version, and embedding model version. The endpoint supports `limit` (1–100) and `offset`.

```sh
curl --get -H "Authorization: Bearer $BROSKI_DEV_TOKEN" \
  --data-urlencode "q=What is my policy limit?" \
  --data-urlencode "top_k=5" \
  http://127.0.0.1:8000/search
```

`/search` accepts optional `document_type` and `document_id` filters. It combines exact pgvector cosine search with PostgreSQL full-text search by reciprocal rank fusion. Exact identifiers such as `PX-4917` are promoted when their literal text appears. This is **evidence retrieval**, not an answer: scores rank passages and are not probabilities of correctness. PostgreSQL full-text search is the lexical baseline, not BM25. No approximate vector index or reranker is needed at the current corpus size.

The API and worker use the same local FastEmbed `BAAI/bge-small-en-v1.5` model. Both images prefetch weights at build time and load a fixed local model directory at runtime; no document text is sent to an embedding provider. Model bytes determine the stored version, so mismatched embeddings are excluded from search until reindexed. Parser-version changes also requeue documents. This first baseline is English-focused; evaluate other languages before promising support.

Deletion immediately hides the row from all vault endpoints, cancels its job, removes extracted chunks, and moves the original into `data/.deleted`. Automated retention/purging remains a later release task. Do not expose this development token or API to the internet; production OIDC or a verified bot identity must replace it.

## Verification

API tests pass in Python 3.11. Live disposable-container verification also passes: Flyway applies V1–V4 to a fresh database, repeated migration is idempotent, the previous extension-only database is adopted, and an altered checksum is rejected. The API integration check covered invalid authentication, synthetic PDF upload/list, byte-identical private download, soft deletion, post-delete denial, and another owner's record being excluded from list/detail responses.

For T03, the disposable migration check also verifies V3 and backfills uploads created under V2. The isolated worker format check is:

```sh
docker build -f backend/Dockerfile.worker -t broski-worker-check backend
docker run --rm --network none -e PYTHONPATH=/app -v "$PWD/infra:/checks:ro" \
  broski-worker-check python /checks/verify_ingestion_formats.py
```

It checks synthetic digital/scanned PDFs, an image, DOCX headings/tables, a note, a corrupt PDF, and a 300-page book with page-limit rejection. A local integration run also checked queued → ready, one chunk after an expired lease was reclaimed, and zero chunks after deletion. Representative insurance/identity scans still need evaluation before release.

For T04, a disposable live stack verified upload → local embedding → ready → search, exact-code lookup, document-type filtering, second-owner exclusion, model-version reindexing after restart, and removal from search after deletion. Ten labeled synthetic questions gave top-1 vector 9/10, PostgreSQL lexical 7/10, and hybrid 10/10. The questions and limitations are recorded in [the retrieval baseline](docs/RETRIEVAL_EVALUATION.md). This small English sample is a regression baseline, not a policy-answer quality claim.

The current host has Node 18. Frontend setup will use Node 22.12+ (or a supported later version), matching Vite's runtime requirements; no global Node installation was changed in T01.

## Data boundary

Embedding inference runs locally; no external model provider is connected. Do not put personal files or credentials in this repository. Production login, owner-scoped file access, private storage, and the processing-provider policy must be implemented before using Broski remotely with personal documents.
