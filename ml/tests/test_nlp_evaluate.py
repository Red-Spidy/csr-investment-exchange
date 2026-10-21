"""Gold answers for evaluation, and the scoring loop around a reader."""

import pandas as pd

from nlp.data import METRIC_LABELS, Example
from nlp.evaluate import evaluate, gold_fields

PROJECTS = pd.DataFrame({
    "project_id": [1], "baseline": [48.0], "target": [57.0], "beneficiaries": [3200],
    "requested_amount": [1_800_000], "duration_months": [9], "district": ["Gaya"],
    "sdgs": [[2, 4]], "metric_name": ["attendance_rate"], "split": ["test"],
}).set_index("project_id")


def _example(spans):
    return Example(1, "text", [2, 4], METRIC_LABELS.index("attendance_rate"), spans, "test", "gemini")


def test_gold_has_true_values_for_stated_fields_and_nothing_for_omitted_ones():
    ex = _example({"baseline": (0, 2), "target": (3, 5), "district": (6, 10)})
    assert gold_fields(ex, PROJECTS.loc[1]) == {
        "baseline": 48.0, "target": 57.0, "district": "Gaya",
        "beneficiaries": None, "amount": None, "duration": None}


def test_a_perfect_reader_scores_perfectly():
    ex = _example({"baseline": (0, 2), "target": (3, 5), "amount": (6, 8), "duration": (9, 10),
                   "beneficiaries": (11, 12), "district": (13, 14)})
    perfect = lambda text: {"sdgs": {2, 4}, "metric": "attendance_rate",
                            "fields": {"baseline": 48, "target": 57, "amount": 1_800_000, "duration": 9,
                                       "beneficiaries": 3200, "district": "Gaya"}}
    r = evaluate(perfect, [ex], PROJECTS)
    assert r["sdg"]["micro_f1"] == 1.0 and r["metric_accuracy"] == 1.0
    assert r["fields"]["accuracy_on_stated"] == 1.0 and r["fields"]["hallucination_rate"] == 0.0
