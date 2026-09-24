from uuid import uuid4

from app.search import combine


def row(document_id, ordinal, text):
    return {
        "document_id": document_id, "ordinal": ordinal, "text": text,
        "page_number": 2, "section_path": "Coverage", "title": "Policy",
        "document_type": "policy", "source_sha256": "a" * 64,
    }


def test_exact_identifier_is_promoted_and_dual_match_is_fused():
    document_id = uuid4()
    semantic = {**row(document_id, 0, "General coverage"), "cosine_similarity": 0.91}
    exact = {**row(document_id, 1, "PX-4917 means expired policy"),
             "cosine_similarity": 0.61}
    keyword = {**row(document_id, 1, "PX-4917 means expired policy"),
               "lexical_rank": 0.2, "exact_identifier_match": True}
    hits = combine([semantic, exact], [keyword], 2)
    assert hits[0].ordinal == 1
    assert hits[0].exact_identifier_match
    assert hits[0].cosine_similarity == 0.61
    assert hits[0].lexical_rank == 0.2
