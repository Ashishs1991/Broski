from unittest.mock import MagicMock

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_liveness_without_database(monkeypatch):
    monkeypatch.delenv("PGPASSWORD", raising=False)
    assert client.get("/health/live").json() == {"status": "ok", "service": "broski"}
    assert client.get("/health/ready").status_code == 503


@pytest.fixture
def configured(monkeypatch):
    for key, value in {
        "PGHOST": "localhost", "PGDATABASE": "broski", "PGUSER": "broski", "PGPASSWORD": "test-secret"
    }.items():
        monkeypatch.setenv(key, value)


def test_database_failure_is_private_and_does_not_break_liveness(monkeypatch, configured):
    def fail(**kwargs):
        raise psycopg.OperationalError("connection failed: test-secret")

    monkeypatch.setattr("app.main.psycopg.connect", fail)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert "test-secret" not in response.text
    assert client.get("/health/live").status_code == 200


@pytest.mark.parametrize("extension_exists, expected_status", [(True, 200), (False, 503)])
def test_readiness_requires_pgvector(monkeypatch, configured, extension_exists, expected_status):
    connect = MagicMock()
    cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (extension_exists,)
    monkeypatch.setattr("app.main.psycopg.connect", connect)
    response = client.get("/health/ready")
    assert response.status_code == expected_status
    cursor.execute.assert_called_once_with(
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
    )
    connect.assert_called_once_with(connect_timeout=3, options="-c statement_timeout=2000")
