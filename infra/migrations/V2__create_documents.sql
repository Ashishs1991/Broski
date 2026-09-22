CREATE TABLE public.documents (
    id uuid PRIMARY KEY,
    owner_id text NOT NULL,
    title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 300),
    document_type text NOT NULL CHECK (
        document_type IN ('book', 'note', 'policy', 'insurance', 'deed', 'identity', 'other')
    ),
    original_filename text NOT NULL CHECK (char_length(original_filename) BETWEEN 1 AND 255),
    media_type text NOT NULL,
    storage_key text NOT NULL UNIQUE,
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    status text NOT NULL DEFAULT 'uploaded' CHECK (
        status IN ('uploaded', 'queued', 'processing', 'ready', 'failed', 'deleted')
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);

CREATE INDEX documents_owner_created_idx
    ON public.documents (owner_id, created_at DESC)
    WHERE deleted_at IS NULL;

