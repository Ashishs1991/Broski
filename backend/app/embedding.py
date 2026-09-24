"""The same local model and input format are used for indexing and queries."""
from functools import lru_cache
import hashlib
import os
from pathlib import Path

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384


@lru_cache
def model():
    from fastembed import TextEmbedding

    path = os.getenv("BROSKI_MODEL_PATH")
    if path:
        return TextEmbedding(model_name=MODEL_NAME, specific_model_path=path)
    return TextEmbedding(model_name=MODEL_NAME,
                         cache_dir=str(Path.home() / ".cache" / "broski"))


@lru_cache
def model_version():
    # FastEmbed 0.8.1's loaded model path keeps local and container versions identical.
    with (Path(model().model._model_dir) / "model_optimized.onnx").open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()[:16]
    return f"{MODEL_NAME}:{digest}"


def embed_passages(chunks: list[dict], title: str) -> list[str]:
    texts = [
        "passage: " + title + (" > " + c["section_path"] if c["section_path"] else "")
        + "\n" + c["text"]
        for c in chunks
    ]
    return [vector_literal(vector) for vector in model().embed(texts)]


def embed_query(query: str) -> str:
    return vector_literal(next(model().embed(["query: " + query])))


def vector_literal(vector) -> str:
    if len(vector) != DIMENSIONS:
        raise ValueError("Embedding model returned the wrong dimension")
    return "[" + ",".join(str(float(value)) for value in vector) + "]"
