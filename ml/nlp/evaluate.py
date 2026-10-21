"""Score any proposal reader -- BERT or the rule baseline -- the same way.

Gold answers come from the synthetic world, not from the text: a field the
proposal stated is scored against its true value; a field it was told to
omit has no answer, so filling it in counts as a hallucination.
"""

from __future__ import annotations

import pandas as pd

from nlp.data import METRIC_LABELS, SDG_LABELS
from nlp.metrics import field_scores, sdg_scores

FIELDS = ("baseline", "target", "beneficiaries", "amount", "duration", "district")
_SOURCE = {"baseline": "baseline", "target": "target", "beneficiaries": "beneficiaries",
           "amount": "requested_amount", "duration": "duration_months", "district": "district"}


def _plain(value):
    return value.item() if hasattr(value, "item") else value


def gold_fields(example, project: pd.Series) -> dict:
    return {f: (_plain(project[_SOURCE[f]]) if f in example.spans else None) for f in FIELDS}


def reading_to_prediction(reading) -> dict:
    return {"sdgs": set(reading.sdgs), "metric": reading.metric_name,
            "fields": {name: f.value for name, f in reading.fields.items()}}


def evaluate(read_fn, examples, projects: pd.DataFrame) -> dict:
    """`read_fn(text)` returns {"sdgs": set, "metric": name, "fields": {name: value}};
    `projects` is indexed by project_id."""
    gold_sdgs, pred_sdgs, gold, pred, metric_hits = [], [], [], [], 0
    for ex in examples:
        out = read_fn(ex.text)
        gold_sdgs.append(set(ex.sdgs))
        pred_sdgs.append(set(out["sdgs"]))
        metric_hits += out["metric"] == METRIC_LABELS[ex.metric]
        gold.append(gold_fields(ex, projects.loc[ex.project_id]))
        pred.append({f: out["fields"].get(f) for f in FIELDS})
    return {
        "n": len(examples),
        "sdg": sdg_scores(gold_sdgs, pred_sdgs, SDG_LABELS),
        "metric_accuracy": round(metric_hits / len(examples), 4) if examples else 0.0,
        "fields": field_scores(gold, pred, FIELDS),
    }
