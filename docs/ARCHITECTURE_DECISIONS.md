# Broski architecture decisions — interview notes

This file records why Broski currently uses each major component and what evidence would make us revisit it. It separates implemented facts from future plans.

## PostgreSQL and pgvector

**Correction to the mental model:** pgvector is not a separate datastore beside PostgreSQL. It is a PostgreSQL extension. PostgreSQL stores document metadata, ownership, lifecycle state, chunks, jobs, and vector columns. Original binaries remain in private file/object storage.

**Interview answer:**

> “For the first Broski deployment, I chose PostgreSQL with pgvector because documents have relational lifecycle and security data as well as embeddings. Keeping ownership, versions, chunks, ingestion state, and vectors in one transactional database reduces the number of services and cross-store cleanup paths. pgvector gives us exact search first and HNSW or IVFFlat when measurements justify ANN. I would move vector serving to a specialized engine only after benchmarks show PostgreSQL is the bottleneck.”

MongoDB is a reasonable alternative when the dominant operational model is flexible aggregate documents and the team already operates it. MongoDB also has vector search, so MongoDB does not automatically imply Milvus.

Milvus is a specialized vector database with scalar filtering, ANN choices, and independent vector-serving scale. MongoDB plus Milvus would introduce two databases whose IDs, ownership filters, updates, and deletions must stay synchronized. That cost is not justified by Broski's current personal-assistant workload. Reconsider Milvus after measuring chunk count, dimensions, filtered recall, write rate, concurrency, P95, and operating cost.

Trade-offs we accept with pgvector: vector workloads share PostgreSQL resources; filtered ANN needs tuning and recall evaluation; very large vector serving may scale less naturally than a dedicated engine. “One database” is a simplicity decision, not a claim that PostgreSQL wins every vector benchmark.

## Python rather than Java for the first service

 Python is chosen intentionally for this learning project because Docling, OCR/ML libraries, embedding SDKs, and RAG experimentation are Python-first, and FastAPI makes a small typed API straightforward. Python is not inherently more scalable than Java, and Java/Spring would be a strong choice for a team standardized on the JVM.

**Interview answer:**

> “I chose Python for the first Broski service because the document and AI ecosystem I need is strongest there, and the project also develops my Python skills. I kept the service small, typed at its API boundary, tested, and backed by language-independent PostgreSQL/Flyway contracts. I would not split out a Java service unless profiling, team ownership, or a JVM-specific integration gave us a concrete reason.”

## No custom web UI initially

Broski's core is channel-independent. The API owns authorization, document lifecycle, retrieval, and citations. A Telegram or Slack adapter translates verified channel events into API operations.

Telegram is the provisional first channel for a one-person assistant; Slack is a better fit for an organization already using workspace identity and administration. Neither is a private transport owned by Broski. Sending an Aadhaar attachment through a bot means the channel provider processes/stores that document under its policies.

The safer default for highly sensitive files is a short-lived, authenticated Broski download rather than uploading the attachment into chat. Because production identity and signed downloads are not built yet, the current API uses a loopback-only development bearer token. Telegram integration comes after the vault and OCR pipeline, and must verify webhook authenticity plus map the Telegram user/chat to an internal owner. Query text never chooses the owner.

## Flyway

Schema changes are application history and must be reproducible. Flyway runs versioned SQL, stores checksums, and blocks API startup if migrations fail. We use SQL directly because PostgreSQL constraints and pgvector objects are part of the design; an ORM abstraction would not remove that database knowledge.

Never edit an applied version. Add the next migration. Production should separate the privileged migration identity from the lower-privilege API identity.

## Current simplifications

- One Python API and later one worker; add services only when independent scaling or failure isolation is measured.
- PostgreSQL-backed jobs later; add Redis/Kafka only when job throughput or delivery semantics require it.
- Local private file storage during development; deployment needs private object storage, authenticated download, backup, and retention policy.
- Development bearer token only on loopback; production requires verified identity.
