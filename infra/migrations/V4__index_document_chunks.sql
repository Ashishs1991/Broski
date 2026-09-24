ALTER TABLE public.document_chunks
    ADD COLUMN embedding vector(384),
    ADD COLUMN embedding_model text,
    ADD COLUMN search_tsv tsvector GENERATED ALWAYS AS
        (to_tsvector('english'::regconfig, text)) STORED;

CREATE INDEX document_chunks_fts_idx
    ON public.document_chunks USING GIN (search_tsv);

-- Existing ready documents must be reprocessed before they can be searched.
UPDATE public.ingestion_jobs j
SET status = 'queued', attempts = 0, available_at = now(),
    lease_until = NULL, lease_token = NULL, error = NULL, updated_at = now()
FROM public.documents d
WHERE d.id = j.document_id AND d.status = 'ready' AND d.deleted_at IS NULL;

UPDATE public.documents SET status = 'queued', updated_at = now()
WHERE status = 'ready' AND deleted_at IS NULL;
