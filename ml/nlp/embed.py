"""Embeddings for pgvector matching.

all-MiniLM-L6-v2: 384 dimensions, CPU-fast, no API cost, works offline once
cached. Not trained here -- this is inference against a pretrained model, which
is why the vector column in the schema is vector(384).

Both sides of the match are embedded through the SAME canonicalisation:
a project's extracted structure, and a company's rulebook fields. Embedding a
long discursive proposal against a short structured rulebook compares unlike
things and matches noticeably worse.
"""

from __future__ import annotations

from functools import lru_cache

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384


@lru_cache(maxsize=1)
def get_model():
    """Loaded once per process. First call downloads ~90MB, then it is cached."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch. Normalised, so cosine distance is what pgvector compares."""
    if not texts:
        return []
    vectors = get_model().encode(
        texts, normalize_embeddings=True, show_progress_bar=False
    )
    return [v.tolist() for v in vectors]


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def rulebook_canonical_text(
    requirement_text: str,
    focus_areas: list[str] | None = None,
    preferred_states: list[str] | None = None,
    target_sdgs: list[int] | None = None,
) -> str:
    """Mirror of ProposalExtraction.canonical_text for the company side."""
    parts = [requirement_text]
    parts.extend(a.replace("_", " ") for a in (focus_areas or []))
    parts.extend(preferred_states or [])
    parts.extend(f"SDG {n}" for n in sorted(target_sdgs or []))
    return " | ".join(p for p in parts if p)


def to_pgvector(vector: list[float]) -> str:
    """psycopg sends a vector column as its text form: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
