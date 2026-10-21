"""BERT inputs and targets for the three proposal readers.

  * SDGs    -- multi-label: one sigmoid per SDG that occurs in the catalogue
  * metric  -- single-label: which outcome the proposal measures
  * fields  -- token tags (B-/I-/O) aligned from the checker's character spans

Proposals longer than BERT's window are split into overlapping chunks; every
chunk carries character offsets so predictions map back to the original text.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from synth.catalog import SECTOR_PROFILE

SDG_LABELS: tuple[int, ...] = tuple(sorted({
    g for profile in SECTOR_PROFILE.values() for sdgs in profile.activities.values() for g in sdgs
}))
METRIC_LABELS: tuple[str, ...] = tuple(m.name for p in SECTOR_PROFILE.values() for m in p.metrics)
METRIC_UNITS: dict[str, str] = {m.name: m.unit for p in SECTOR_PROFILE.values() for m in p.metrics}

# Checker span name -> entity type.
FIELD_ENTITY = {
    "beneficiaries": "BENEFICIARIES",
    "baseline": "BASELINE",
    "target": "TARGET",
    "amount": "AMOUNT",
    "duration": "DURATION",
    "district": "DISTRICT",
}
ENTITY_TYPES: tuple[str, ...] = tuple(FIELD_ENTITY.values())
TAGS: tuple[str, ...] = ("O", *[f"{p}-{e}" for e in ENTITY_TYPES for p in ("B", "I")])
TAG_ID = {t: i for i, t in enumerate(TAGS)}
IGNORE = -100            # positions the loss skips: [CLS], [SEP], padding

MAX_LENGTH = 512
STRIDE = 128


def sdg_vector(sdgs) -> list[float]:
    present = set(sdgs)
    return [1.0 if g in present else 0.0 for g in SDG_LABELS]


@dataclass(frozen=True)
class Example:
    project_id: int
    text: str
    sdgs: list[int]
    metric: int                          # index into METRIC_LABELS
    spans: dict[str, tuple[int, int]]    # checker span name -> (start, end)
    split: str
    provider: str


def build_examples(proposals: list[dict], projects: pd.DataFrame) -> list[Example]:
    """Join generated text (proposals.jsonl) with its labels (projects.csv).
    The split comes from the project, which got it from its NGO."""
    labels = projects.set_index("project_id")
    out = []
    for p in proposals:
        row = labels.loc[p["project_id"]]
        out.append(Example(
            project_id=int(p["project_id"]),
            text=p["text"],
            sdgs=list(row["sdgs"]),
            metric=METRIC_LABELS.index(row["metric_name"]),
            spans={k: tuple(v) for k, v in p["spans"].items()},
            split=str(row["split"]),
            provider=p.get("provider", ""),
        ))
    return out


def _token_tags(offsets, spans: dict[str, tuple[int, int]]) -> list[int]:
    """B- for the token holding a fact's first character, I- for the rest of
    it, O elsewhere. A chunk that starts mid-fact correctly continues with I-."""
    tags = []
    for offset in offsets:
        if offset is None:
            tags.append(IGNORE)
            continue
        s, e = offset
        hit = next(((FIELD_ENTITY[f], a) for f, (a, b) in spans.items() if f in FIELD_ENTITY and s < b and e > a),
                   None)
        if hit is None:
            tags.append(TAG_ID["O"])
        else:
            entity, start = hit
            tags.append(TAG_ID[("B-" if s <= start else "I-") + entity])
    return tags


def encode(tokenizer, text: str, spans: dict[str, tuple[int, int]] | None = None,
           max_length: int = MAX_LENGTH, stride: int = STRIDE) -> list[dict]:
    """Tokenise into overlapping chunks. Each chunk: input_ids, attention_mask,
    offsets (None for special tokens), and token tags when spans are given.

    Windowing is done here rather than by the tokenizer's own overflow
    handling, which in the installed version silently dropped most of a long
    text (2 chunks covering 12% of it). Tokenise once, then slide a window.
    """
    enc = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, verbose=False)
    ids, offsets = enc["input_ids"], [tuple(o) for o in enc["offset_mapping"]]
    body = max_length - 2                 # room for [CLS] and [SEP]
    step = body - stride
    chunks, start = [], 0
    while True:
        end = min(start + body, len(ids))
        window_ids = [tokenizer.cls_token_id, *ids[start:end], tokenizer.sep_token_id]   # BERT-family
        window_offsets = [None, *offsets[start:end], None]
        chunks.append({
            "input_ids": window_ids,
            "attention_mask": [1] * len(window_ids),
            "offsets": window_offsets,
            "labels": None if spans is None else _token_tags(window_offsets, spans),
        })
        if end >= len(ids):
            return chunks
        start += step
