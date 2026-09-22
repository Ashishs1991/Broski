# Broski

A personal document assistant: retrieve original files and answer from your books, notes, policies, and other documents with citations.

## Current state

**Task T01: API/database foundation.** Implemented: FastAPI liveness and Postgres/pgvector readiness checks, local Compose configuration, dependency pins, and API tests. Upload, login, OCR, search, chat, and the React interface are **not implemented yet**. This is a local development skeleton, not the deployable MVP.

Read [PROJECT_PLAN.md](PROJECT_PLAN.md) for the updated MVP scope, stack, task order, and acceptance criteria.

## Run locally with Docker

Requires Docker Engine/Desktop running with Compose available.

1. Copy `.env.example` to `.env`.
2. Set `PGPASSWORD` in `.env` to a unique local password. A missing/empty password makes Compose reject startup.
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

Ports bind to loopback. The database is persisted in a Docker volume. The SQL bootstrap runs only when that database volume is first initialized. Changing the `.env` password later does not change an existing database user's password. Do not delete persistent volumes to troubleshoot real data without a backup.

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

## Verification for T01

API tests were run in an isolated Python 3.11 environment. Docker was installed but its daemon was unavailable when this task was created, so a live database connection and Compose startup have not yet been verified. Run the two health checks after starting Docker to complete that integration check.

The current host has Node 18. Frontend setup will use Node 22.12+ (or a supported later version), matching Vite's runtime requirements; no global Node installation was changed in T01.

## Data boundary

No user documents are uploaded or processed in T01, and no model provider is connected. Do not put personal files or credentials in this repository. Production login, owner-scoped file access, private storage, and the processing-provider policy must be implemented before using Broski remotely with personal documents.
