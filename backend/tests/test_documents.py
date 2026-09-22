import os
from pathlib import Path
import zipfile

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.documents import clean_filename, current_owner, validate_file
from app.main import app

client = TestClient(app)


def test_document_routes_fail_closed_without_auth_configuration(monkeypatch):
    monkeypatch.delenv("BROSKI_DEV_TOKEN", raising=False)
    monkeypatch.delenv("BROSKI_DEV_OWNER_ID", raising=False)
    response = client.get("/documents")
    assert response.status_code == 503


def test_development_bearer_token(monkeypatch):
    monkeypatch.setenv("BROSKI_DEV_TOKEN", "expected-token")
    monkeypatch.setenv("BROSKI_DEV_OWNER_ID", "owner-a")
    assert current_owner("Bearer expected-token") == "owner-a"
    with pytest.raises(HTTPException) as error:
        current_owner("Bearer wrong-token")
    assert error.value.status_code == 401


@pytest.mark.parametrize("unsafe", ["", ".", "..", "bad\x00.pdf"])
def test_rejects_unsafe_filenames(unsafe):
    with pytest.raises(HTTPException):
        clean_filename(unsafe)


def test_keeps_only_the_filename_component():
    assert clean_filename("../../policy.PDF") == ("policy.PDF", ".pdf")


@pytest.mark.parametrize(
    ("name", "content", "media_type"),
    [
        ("policy.pdf", b"%PDF-1.7\nexample", "application/pdf"),
        ("scan.png", b"\x89PNG\r\n\x1a\nexample", "image/png"),
        ("scan.jpg", b"\xff\xd8\xffexample", "image/jpeg"),
        ("notes.md", "# Notes\nhello".encode(), "text/markdown"),
    ],
)
def test_validates_supported_content(tmp_path, name, content, media_type):
    path = tmp_path / name
    path.write_bytes(content)
    assert validate_file(path, path.suffix) == media_type


def test_validates_docx_structure(tmp_path):
    path = tmp_path / "policy.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", "<document/>")
    assert "wordprocessingml" in validate_file(path, ".docx")


def test_rejects_extension_spoofing(tmp_path):
    path = tmp_path / "not-really.pdf"
    path.write_bytes(b"plain text")
    with pytest.raises(HTTPException) as error:
        validate_file(path, ".pdf")
    assert error.value.status_code == 415
