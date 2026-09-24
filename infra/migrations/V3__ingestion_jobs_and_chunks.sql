CREATE TABLE public.ingestion_jobs (
    document_id uuid PRIMARY KEY REFERENCES public.documents(id) ON DELETE CASCADE,
    status text NOT NULL CHECK (status IN ('queued', 'processing', 'complete', 'failed', 'cancelled')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at timestamptz NOT NULL DEFAULT now(),
    lease_until timestamptz,
    lease_token uuid,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ingestion_jobs_claim_idx ON public.ingestion_jobs (available_at)
    WHERE status IN ('queued', 'processing');

CREATE TABLE public.document_chunks (
    document_id uuid NOT NULL REFERENCES public.documents(id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    text text NOT NULL CHECK (length(text) > 0),
    page_number integer CHECK (page_number > 0),
    section_path text,
    source_sha256 char(64) NOT NULL,
    parser_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, ordinal)
);

CREATE INDEX document_chunks_document_idx ON public.document_chunks (document_id);

INSERT INTO public.ingestion_jobs (document_id, status)
SELECT id, 'queued' FROM public.documents
WHERE status = 'uploaded' AND deleted_at IS NULL;

UPDATE public.documents SET status = 'queued', updated_at = now()
WHERE status = 'uploaded' AND deleted_at IS NULL;
