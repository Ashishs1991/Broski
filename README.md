# Broski

A personal document assistant: retrieve original files and answer from your books, notes, policies, and other documents with citations.

## Current state

**Task T01: API/database foundation.** Implemented: FastAPI liveness and Postgres/pgvector readiness checks, local Compose configuration, versioned Flyway migrations, dependency pins, and API tests. Upload, login, OCR, search, chat, and the React interface are **not implemented yet**. This is a local development skeleton, not the deployable MVP.

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

Ports bind to loopback. The database is persisted in a Docker volume. Flyway applies pending migrations before API startup. It records versions/checksums in `flyway_history.flyway_schema_history`. Changing the `.env` password later does not change an existing database user's password. Do not delete persistent volumes to troubleshoot real data without a backup.

## Database migrations with Flyway

SQL migrations live in `infra/migrations/`. `V1__enable_pgvector.sql` enables the vector extension in `public`. No document/chunk tables or embedding dimensions are chosen yet; add those with their implementation tasks.

Startup order is `db healthy → migrate succeeds → api starts`. A failed migration prevents a new API container from starting. For an already-running application, apply migrations explicitly as part of each release; Compose does not pause or restart a running API just because a migration file changed.

```sh
# Normal local startup, including migration
docker compose up --build

# Inspect, validate, or apply migrations to the configured local database
docker compose run --rm migrate info
docker compose run --rm migrate validate
docker compose run --rm migrate migrate
```

Name future files `V2__create_documents.sql`, `V3__...sql`, and so on. Never edit or rename an applied versioned migration: add a new version. A later deployment should use a dedicated migration identity and a less privileged API identity; local Compose currently uses one development database owner.

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

## Verification

API tests were run in an isolated Python 3.11 environment. The Flyway Compose configuration validates, and the migration test runner passes Python syntax checking. Live Flyway/PostgreSQL integration is not yet verified: Docker Desktop was started, but downloading the required images did not complete during setup. Run `python3 infra/test_migrations.py` after the images are available, then start the app and check both health endpoints.

The current host has Node 18. Frontend setup will use Node 22.12+ (or a supported later version), matching Vite's runtime requirements; no global Node installation was changed in T01.

## Data boundary

No user documents are uploaded or processed in T01, and no model provider is connected. Do not put personal files or credentials in this repository. Production login, owner-scoped file access, private storage, and the processing-provider policy must be implemented before using Broski remotely with personal documents.
