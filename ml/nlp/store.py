"""Persist NLP output into PostgreSQL.

Extractions are cached in the database on purpose: the scoring pipeline runs
once per proposal, and every later read -- the demo included -- comes from this
table. A review demo must never depend on a live API call.
"""

from __future__ import annotations

import json
import os

import psycopg

from embed import embed_text, rulebook_canonical_text, to_pgvector
from extract import ExtractionResult

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://csr:csr@localhost:5433/csr_exchange"
)

_UPSERT = """
INSERT INTO project_extractions
    (project_id, goals, target_metric, beneficiaries, geography, budget_lines,
     duration_months, sdgs, sdg_confidence, red_flags, canonical_text, embedding,
     raw_response, model_version, prompt_version)
VALUES (%(project_id)s, %(goals)s, %(target_metric)s, %(beneficiaries)s,
        %(geography)s, %(budget_lines)s, %(duration_months)s, %(sdgs)s,
        %(sdg_confidence)s, %(red_flags)s, %(canonical_text)s, %(embedding)s,
        %(raw_response)s, %(model_version)s, %(prompt_version)s)
ON CONFLICT (project_id) DO UPDATE SET
    goals           = EXCLUDED.goals,
    target_metric   = EXCLUDED.target_metric,
    beneficiaries   = EXCLUDED.beneficiaries,
    geography       = EXCLUDED.geography,
    budget_lines    = EXCLUDED.budget_lines,
    duration_months = EXCLUDED.duration_months,
    sdgs            = EXCLUDED.sdgs,
    sdg_confidence  = EXCLUDED.sdg_confidence,
    red_flags       = EXCLUDED.red_flags,
    canonical_text  = EXCLUDED.canonical_text,
    embedding       = EXCLUDED.embedding,
    raw_response    = EXCLUDED.raw_response,
    model_version   = EXCLUDED.model_version,
    prompt_version  = EXCLUDED.prompt_version,
    extracted_at    = now()
RETURNING project_id;
"""


def connect(dsn: str | None = None) -> psycopg.Connection:
    return psycopg.connect(dsn or DATABASE_URL)


def _json_or_none(model) -> str | None:
    return json.dumps(model.model_dump()) if model is not None else None


def store_extraction(
    conn: psycopg.Connection,
    project_id: int,
    result: ExtractionResult,
    title: str = "",
    embed: bool = True,
) -> int:
    """Write one extraction, with its canonical-text embedding, to the database."""
    ex = result.extraction
    canonical = ex.canonical_text(title)
    vector = to_pgvector(embed_text(canonical)) if embed and canonical else None

    with conn.cursor() as cur:
        cur.execute(
            _UPSERT,
            {
                "project_id": project_id,
                "goals": json.dumps(ex.goals),
                "target_metric": _json_or_none(ex.target_metric),
                "beneficiaries": _json_or_none(ex.beneficiaries),
                "geography": _json_or_none(ex.geography),
                "budget_lines": json.dumps([b.model_dump() for b in ex.budget_lines]),
                "duration_months": ex.duration_months,
                "sdgs": ex.sdgs,
                "sdg_confidence": json.dumps(ex.sdg_confidence),
                "red_flags": json.dumps(ex.red_flags),
                "canonical_text": canonical,
                "embedding": vector,
                "raw_response": json.dumps(ex.model_dump()),
                "model_version": result.model_version,
                "prompt_version": result.prompt_version,
            },
        )
        stored = cur.fetchone()[0]
    conn.commit()
    return stored


def embed_rulebook(conn: psycopg.Connection, rulebook_id: int) -> bool:
    """Compute and store a rulebook's embedding through the same canonicalisation
    used for projects. Both sides must be embedded the same way or the cosine
    comparison is meaningless."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT requirement_text, focus_areas, preferred_states, target_sdgs "
            "FROM csr_rulebooks WHERE id = %s",
            (rulebook_id,),
        )
        row = cur.fetchone()
        if row is None:
            return False

        canonical = rulebook_canonical_text(row[0], row[1], row[2], row[3])
        cur.execute(
            "UPDATE csr_rulebooks SET embedding = %s WHERE id = %s",
            (to_pgvector(embed_text(canonical)), rulebook_id),
        )
    conn.commit()
    return True


def pending_projects(conn: psycopg.Connection) -> list[dict]:
    """Projects awaiting NLP extraction."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.id, p.title, p.sector, p.proposal_text FROM projects p "
            "LEFT JOIN project_extractions e ON e.project_id = p.id "
            "WHERE e.project_id IS NULL ORDER BY p.id"
        )
        return [
            {"id": r[0], "title": r[1], "sector": r[2], "proposal_text": r[3]}
            for r in cur.fetchall()
        ]
