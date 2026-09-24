from app.extract import extract, split_blocks
from app import documents
from uuid import uuid4


def test_markdown_notes_keep_heading_and_content(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Coverage\n\nPolicy limit is ₹5 lakh.", encoding="utf-8")
    chunks = extract(path, 300)
    assert chunks[0]["section_path"] == "Coverage"
    assert "₹5 lakh" in chunks[0]["text"]
    assert chunks[0]["page_number"] is None


def test_large_table_repeats_header_in_each_chunk():
    table = "| Code | Meaning |\n| --- | --- |\n" + "\n".join(
        f"| PX-{n:04d} | explanation for code {n} |" for n in range(200)
    )
    chunks = split_blocks(table, 2)
    assert len(chunks) > 1
    assert all(chunk["text"].startswith("| Code | Meaning |") for chunk in chunks)
    assert all(chunk["page_number"] == 2 for chunk in chunks)


def test_public_processing_status_uses_document_state(monkeypatch):
    class Database:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def execute(self, *_):
            return self

        def fetchone(self):
            return {"status": "ready", "attempts": 1, "error": None}

    monkeypatch.setattr(documents, "owned_document",
                        lambda *_: {"media_type": "application/pdf"})
    monkeypatch.setattr(documents, "connection", Database)
    result = documents.get_processing_status(uuid4(), "owner")
    assert result.status == "ready"
    assert result.review_extracted_text
