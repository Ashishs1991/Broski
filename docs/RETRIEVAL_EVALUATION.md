# Broski retrieval baseline

25 September 2026 · T04 local evaluation

Three synthetic Markdown documents were uploaded through the API: a health policy with three chunks, an error-code table with one chunk, and password-reset notes with one chunk. The worker indexed all five chunks with the same local 384-dimensional model used by the query API. A second owner's synthetic record was inserted to test isolation.

| Question | Expected evidence |
|---|---|
| What is the sum insured? | Policy, Health Insurance Schedule |
| How much is the deductible? | Policy, Health Insurance Schedule |
| Is cosmetic surgery excluded? | Policy, Hospital Coverage |
| When should hospital bills be submitted? | Policy, Claims |
| Is inpatient hospitalisation covered? | Policy, Hospital Coverage |
| What does PX-4917 mean? | Error Codes table |
| How do I resolve PX-4918? | Error Codes table |
| How long is the password reset link valid? | Password Reset note |
| Can a reset link be reused? | Password Reset note |
| What is the waiting period? | Policy, Hospital Coverage |

| Candidate ranking | Correct evidence at rank 1 |
|---|---:|
| Exact pgvector cosine | 9/10 |
| PostgreSQL full-text | 7/10 |
| Combined reciprocal rank fusion | 10/10 |

The combined search promoted literal error-code matches. Filtering to another owner's document returned no hits; its evidence endpoint returned 404. Deleting the synthetic policy removed its chunks and caused a document-filtered search to return no hits. Restarting with a changed embedding-model version requeued and rebuilt previously ready documents before search exposed them again.

This is a **regression baseline**, not a production quality score. Five easy English chunks cannot represent scanned policies, conflicting schedules, exclusions, or ambiguous questions. Cosine similarity and fusion scores rank passages; neither is a probability that an answer is correct. PostgreSQL full-text search is the lexical baseline, not BM25. Exact vector search avoids approximate-index recall loss at this small corpus size.

Before release, evaluate at least 20 labeled questions on representative documents, including tables, amounts, exclusions, multiple policies, missing evidence, OCR mistakes, exact identifiers, and cross-owner attempts. Track evidence recall separately from answer accuracy. Add HNSW or a reranker only if measured corpus size, latency, or recall warrants it.

**Interview-ready answer:** “I indexed page-linked chunks in PostgreSQL with local 384-dimensional embeddings and full-text search. At query time I restrict candidates to the authenticated owner, combine semantic and lexical rankings, and promote literal identifiers such as error codes. I started with exact pgvector search because the personal corpus is small; approximate indexing would add a recall trade-off before we have a latency problem. The first ten-question synthetic baseline favored the hybrid ranking, but I would validate it on real scans and policy clauses before making quality claims.”
