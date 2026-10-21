"""Metrics for the report, kept dependency-free so every number can be checked
by hand (test_nlp_metrics.py works each one out in a comment).

Field outcomes:
  correct       the text stated it and the reader got it
  wrong         the text stated it and the reader got a different value
  missed        the text stated it and the reader found nothing
  hallucinated  the text never stated it and the reader filled it in  <- the costly one
  correct_null  the text never stated it and the reader left it empty
"""

from __future__ import annotations

OUTCOMES = ("correct", "wrong", "missed", "hallucinated", "correct_null")


def _f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def sdg_scores(gold: list[set], pred: list[set], labels) -> dict:
    per_sdg, total = {}, [0, 0, 0]
    for label in labels:
        tp = sum(label in g and label in p for g, p in zip(gold, pred))
        fp = sum(label not in g and label in p for g, p in zip(gold, pred))
        fn = sum(label in g and label not in p for g, p in zip(gold, pred))
        precision, recall, f1 = _f1(tp, fp, fn)
        per_sdg[label] = {"support": tp + fn, "precision": round(precision, 4),
                          "recall": round(recall, 4), "f1": round(f1, 4)}
        total = [total[0] + tp, total[1] + fp, total[2] + fn]
    occurring = [v["f1"] for v in per_sdg.values() if v["support"] > 0]
    precision, recall, f1 = _f1(*total)
    return {
        "micro_precision": round(precision, 4),
        "micro_recall": round(recall, 4),
        "micro_f1": round(f1, 4),
        "macro_f1": round(sum(occurring) / len(occurring), 4) if occurring else 0.0,
        "exact_match": round(sum(set(g) == set(p) for g, p in zip(gold, pred)) / len(gold), 4) if gold else 0.0,
        "per_sdg": per_sdg,
    }


def _same(a, b) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return str(a).strip().lower() == str(b).strip().lower()
    return abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(b)))


def _outcome(g, p) -> str:
    if g is None:
        return "correct_null" if p is None else "hallucinated"
    if p is None:
        return "missed"
    return "correct" if _same(g, p) else "wrong"


def field_scores(gold: list[dict], pred: list[dict], fields) -> dict:
    counts = dict.fromkeys(OUTCOMES, 0)
    per_field = {f: dict.fromkeys(OUTCOMES, 0) for f in fields}
    for g_doc, p_doc in zip(gold, pred):
        for f in fields:
            outcome = _outcome(g_doc.get(f), p_doc.get(f))
            counts[outcome] += 1
            per_field[f][outcome] += 1
    unstated = counts["hallucinated"] + counts["correct_null"]
    stated = counts["correct"] + counts["wrong"] + counts["missed"]
    return {
        "counts": counts,
        "hallucination_rate": round(counts["hallucinated"] / unstated, 4) if unstated else 0.0,
        "accuracy_on_stated": round(counts["correct"] / stated, 4) if stated else 0.0,
        "per_field": per_field,
    }
