"""Local development foundation. Document and authentication routes follow in T02."""

import os

import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Broski", version="0.1.0")


@app.get("/health/live")
def live():
    """Liveness does not depend on a healthy database."""
    return {"status": "ok", "service": "broski"}


@app.get("/health/ready")
def ready():
    """Check Postgres and pgvector without exposing connection credentials."""
    if not all(os.environ.get(key) for key in ("PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD")):
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    try:
        with psycopg.connect(connect_timeout=3, options="-c statement_timeout=2000") as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
                row = cursor.fetchone()
                if row and row[0]:
                    return {"status": "ready", "database": "ok", "pgvector": "ok"}
    except psycopg.Error:
        # Connection errors may contain credentials or topology; keep them out of responses.
        pass
    return JSONResponse(status_code=503, content={"status": "not_ready"})
