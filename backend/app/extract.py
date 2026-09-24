"""Extract one untrusted original in a time-limited worker subprocess."""
import json
from pathlib import Path
import re
import subprocess
import sys

# ponytail: character cap approximates the model's 512-token window; use token-aware
# splitting if real documents show tail truncation.
MAX_CHARS = 1800
MAX_EXTRACTED_CHARS = 2_000_000


def split_blocks(markdown: str, page_number: int | None):
    section = None
    chunks = []
    current = ""
    current_section = None
    for block in re.split(r"\n\s*\n", markdown):
        block = block.strip()
        if not block:
            continue
        heading = block.startswith("#")
        if heading and current:
            chunks.append({"text": current, "page_number": page_number, "section_path": current_section})
            current = ""
        if heading:
            section = block.splitlines()[0].lstrip("# ").strip() or section
        parts = [block]
        if len(block) > MAX_CHARS:
            if block.startswith("|"):
                lines = block.splitlines()
                header = "\n".join(lines[:2])
                parts = []
                part = header
                for row in lines[2:]:
                    if len(part) + len(row) + 1 > MAX_CHARS:
                        parts.append(part)
                        part = header
                    part += "\n" + row
                parts.append(part)
            else:
                parts = [block[i:i + MAX_CHARS] for i in range(0, len(block), MAX_CHARS)]
        for part in parts:
            if current and len(current) + len(part) + 2 > MAX_CHARS:
                chunks.append({"text": current, "page_number": page_number, "section_path": current_section})
                current = ""
            if not current:
                current_section = section
            else:
                current += "\n\n"
            current += part
    if current:
        chunks.append({"text": current, "page_number": page_number, "section_path": current_section})
    return chunks


def word_markdown(path: Path):
    from docx import Document
    from docx.table import Table

    blocks = []
    for item in Document(path).iter_inner_content():
        if isinstance(item, Table):
            rows = [[cell.text.replace("|", "\\|").replace("\n", " ") for cell in row.cells]
                    for row in item.rows]
            if rows:
                blocks.append("| " + " | ".join(rows[0]) + " |\n"
                              + "| " + " | ".join(["---"] * len(rows[0])) + " |\n"
                              + "\n".join("| " + " | ".join(row) + " |" for row in rows[1:]))
        elif item.text.strip():
            level = item.style.name
            prefix = "#" * int(level[-1]) + " " if level.startswith("Heading ") and level[-1].isdigit() else ""
            blocks.append(prefix + item.text)
    return "\n\n".join(blocks)


def pdf_pages(path: Path, max_pages: int):
    import pymupdf

    pages = []
    with pymupdf.open(path) as document:
        if document.is_encrypted:
            raise ValueError("Encrypted PDFs are unsupported")
        if len(document) > max_pages:
            raise ValueError(f"PDF exceeds {max_pages} page limit")
        for number, page in enumerate(document, start=1):
            content = page.get_text(sort=True).strip()
            if not content:
                image = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
                result = subprocess.run(
                    ["tesseract", "stdin", "stdout", "-l", "eng"],
                    input=image.tobytes("png"), check=True, capture_output=True, timeout=120,
                )
                content = result.stdout.decode("utf-8")
            else:
                tables = page.find_tables()
                for table in tables:
                    content += "\n\n" + table.to_markdown()
            pages.append((number, content))
    return pages


def extract(path: Path, max_pages: int):
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        pages = [(None, path.read_text(encoding="utf-8"))]
    elif suffix == ".docx":
        pages = [(None, word_markdown(path))]
    elif suffix == ".pdf":
        pages = pdf_pages(path, max_pages)
    else:
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", "eng"],
            check=True, capture_output=True, text=True, timeout=120,
        )
        pages = [(1, result.stdout)]
    if sum(len(content) for _, content in pages) > MAX_EXTRACTED_CHARS:
        raise ValueError("Extracted text exceeds processing limit")
    chunks = [chunk for page, content in pages for chunk in split_blocks(content, page)]
    if not chunks:
        raise ValueError("No readable text found; check the scan or file")
    return chunks


if __name__ == "__main__":
    source, output, limit = sys.argv[1:]
    Path(output).write_text(json.dumps(extract(Path(source), int(limit))), encoding="utf-8")
