"""Owner-scoped evidence search. Scores rank evidence; they are not answer confidence."""
from typing import Annotated
from uuid import UUID
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.documents import DocumentType, connection, current_owner
from app.embedding import embed_query, model_version

router = APIRouter(tags=["search"])
IDENTIFIER = re.compile(r"\b[A-Z]{2,10}[-_]\d{2,12}\b", re.IGNORECASE)
FIELDS = """c.document_id, c.ordinal, c.text, c.page_number, c.section_path,
            d.title, d.document_type, c.source_sha256"""


class EvidenceHit(BaseModel):
    document_id: UUID
    ordinal: int
    title: str
    document_type: DocumentType
    text: str
    page_number: int | None
    section_path: str | None
    source_sha256: str
    cosine_similarity: float | None = None
    lexical_rank: float | None = None
    exact_identifier_match: bool = False
    retrieval_score: float


def combine(vector_rows: list[dict], lexical_rows: list[dict], limit: int) -> list[EvidenceHit]:
    hits = {}
    for kind, rows in (("vector", vector_rows), ("lexical", lexical_rows)):
        for rank, row in enumerate(rows, start=1):
            key = (row["document_id"], row["ordinal"])
            if key not in hits:
                hits[key] = {**row, "retrieval_score": 0.0}
            hits[key]["retrieval_score"] += 1 / (60 + rank)
            if kind == "vector":
                hits[key]["cosine_similarity"] = row["cosine_similarity"]
            else:
                hits[key]["lexical_rank"] = row["lexical_rank"]
                hits[key]["exact_identifier_match"] = row["exact_identifier_match"]
    ordered = sorted(
        hits.values(),
        key=lambda row: (row.get("exact_identifier_match", False), row["retrieval_score"]),
        reverse=True,
    )
    return [EvidenceHit(**row) for row in ordered[:limit]]


@router.get("/search", response_model=list[EvidenceHit])
def search(
    q: Annotated[str, Query(max_length=500)],
    owner: Annotated[str, Depends(current_owner)],
    top_k: Annotated[int, Query(ge=1, le=20)] = 5,
    document_type: DocumentType | None = None,
    document_id: UUID | None = None,
):
    query = q.strip()
    if not query:
        raise HTTPException(422, "Query cannot be empty")
    vector = embed_query(query)
    match = IDENTIFIER.search(query)
    identifier = match.group(0) if match else None
    clauses = ["d.owner_id = %s", "d.deleted_at IS NULL", "d.status = 'ready'",
               "c.embedding_model = %s"]
    filters = [owner, model_version()]
    if document_type:
        clauses.append("d.document_type = %s")
        filters.append(document_type.value)
    if document_id:
        clauses.append("d.id = %s")
        filters.append(document_id)
    where = " AND ".join(clauses)
    candidates = max(20, top_k * 4)
    with connection() as database:
        vector_rows = database.execute(f"""
            SELECT {FIELDS}, 1 - (c.embedding <=> %s::vector) AS cosine_similarity
            FROM public.document_chunks c
            JOIN public.documents d ON d.id = c.document_id
            WHERE {where} AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> %s::vector LIMIT %s
        """, [vector, *filters, vector, candidates]).fetchall()
        lexical_rows = database.execute(f"""
            SELECT {FIELDS},
                   ts_rank_cd(c.search_tsv, plainto_tsquery('english', %s)) AS lexical_rank,
                   COALESCE(strpos(lower(c.text), lower(%s)) > 0, false) AS exact_identifier_match
            FROM public.document_chunks c
            JOIN public.documents d ON d.id = c.document_id
            WHERE {where}
              AND (c.search_tsv @@ plainto_tsquery('english', %s)
                   OR COALESCE(strpos(lower(c.text), lower(%s)) > 0, false))
            ORDER BY exact_identifier_match DESC, lexical_rank DESC LIMIT %s
        """, [query, identifier, *filters, query, identifier, candidates]).fetchall()
    return combine(vector_rows, lexical_rows, top_k)
