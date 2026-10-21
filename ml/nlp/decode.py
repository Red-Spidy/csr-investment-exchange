"""From per-token tag scores back to field values in the proposal's own text.

Overlapping chunks see some tokens twice; their scores are averaged so a fact
in the overlap is decoded once. Each field keeps its single most confident
span. A field with no span stays absent -- that is the abstention the
pipeline turns into a red flag, never a guessed value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from nlp.data import FIELD_ENTITY, TAGS
from textgen.checker import find_numbers

ENTITY_FIELD = {entity: field for field, entity in FIELD_ENTITY.items()}
_MULTIPLIER = re.compile(r"\b(lakhs?|lacs?|crores?|million|mn)\b", re.IGNORECASE)
_MULTIPLIER_AFTER = re.compile(r"\s*(lakhs?|lacs?|crores?|million|mn)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Field:
    value: float | int | str
    text: str
    start: int
    end: int
    confidence: float


def merge_chunks(chunks: list[dict], chunk_scores: list) -> tuple[list[tuple[int, int]], np.ndarray]:
    """One row per distinct token of the original text (keyed by its character
    offsets), with scores averaged over every chunk that contained it."""
    totals: dict[tuple[int, int], list] = {}
    for chunk, scores in zip(chunks, chunk_scores):
        for offset, row in zip(chunk["offsets"], np.asarray(scores, dtype=float)):
            if offset is None:
                continue
            if offset in totals:
                totals[offset][0] += row
                totals[offset][1] += 1
            else:
                totals[offset] = [row.copy(), 1]
    offsets = sorted(totals)
    if not offsets:
        return [], np.zeros((0, len(TAGS)))
    return offsets, np.stack([totals[o][0] / totals[o][1] for o in offsets])


def _value(field: str, text: str, start: int, end: int):
    span = text[start:end]
    if field == "district":
        return span.strip() or None
    if field == "amount" and not _MULTIPLIER.search(span):
        # A tag that stops at "12" in "Rs 12 lakh" still means 12 lakh: read on
        # into the multiplier, as the duration does into "years".
        follows = _MULTIPLIER_AFTER.match(text[end:end + 12])
        if follows:
            span += follows.group(0)
    numbers = find_numbers(span)
    if not numbers:
        return None
    value = numbers[0].value
    if field == "duration" and text[end:end + 8].lower().lstrip(" -").startswith("year"):
        value *= 12
    return int(value) if value == int(value) else value


def decode_fields(text: str, offsets: list[tuple[int, int]], scores: np.ndarray) -> dict[str, Field]:
    """B-/I- runs become spans; each field keeps its most confident span."""
    spans: list[list] = []          # [entity, start, end, confidences]
    current = None
    for (s, e), row in zip(offsets, scores):
        tag = TAGS[int(np.argmax(row))]
        if tag == "O":
            current = None
            continue
        prefix, entity = tag.split("-", 1)
        if prefix == "I" and current is not None and current[0] == entity:
            current[2] = e
            current[3].append(float(np.max(row)))
        else:
            current = [entity, s, e, [float(np.max(row))]]
            spans.append(current)

    best: dict[str, tuple[int, int, float]] = {}
    for entity, s, e, confidences in spans:
        confidence = float(np.mean(confidences))
        if entity not in best or confidence > best[entity][2]:
            best[entity] = (s, e, confidence)

    fields = {}
    for entity, (s, e, confidence) in best.items():
        name = ENTITY_FIELD[entity]
        value = _value(name, text, s, e)
        if value is not None:
            fields[name] = Field(value, text[s:e], s, e, round(confidence, 4))
    return fields
