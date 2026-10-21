"""Report metrics, every expected value worked out by hand in a comment."""

import pytest

from nlp.metrics import field_scores, sdg_scores


def test_sdg_precision_recall_f1_by_hand():
    gold = [{3, 5}, {4}, {6}]
    pred = [{3}, {4, 6}, {6}]
    r = sdg_scores(gold, pred, labels=(3, 4, 5, 6))
    # SDG 3: tp 1 fp 0 fn 0 -> P 1, R 1, F1 1
    # SDG 4: tp 1 -> F1 1
    # SDG 5: tp 0 fn 1 -> F1 0
    # SDG 6: tp 1 fp 1 -> P 0.5, R 1, F1 2*0.5*1/1.5 = 0.6667
    assert r["per_sdg"][6]["f1"] == pytest.approx(0.6667, abs=1e-4)
    assert r["per_sdg"][5]["f1"] == 0.0
    # micro: tp 3, fp 1, fn 1 -> P 0.75, R 0.75, F1 0.75
    assert r["micro_f1"] == pytest.approx(0.75)
    # macro over labels that occur in gold: (1 + 1 + 0 + 0.6667) / 4 = 0.6667
    assert r["macro_f1"] == pytest.approx(0.6667, abs=1e-4)
    # exact match: only proposal 3 has the identical set -> 1/3
    assert r["exact_match"] == pytest.approx(1 / 3, abs=1e-4)


def test_field_outcomes_and_hallucination_rate_by_hand():
    gold = [{"baseline": 48, "target": 57, "beneficiaries": None, "district": "Gaya"},
            {"baseline": None, "target": 12, "beneficiaries": 900, "district": "Pakur"}]
    pred = [{"baseline": 48, "target": 60, "beneficiaries": 3000, "district": "gaya"},
            {"baseline": None, "target": 12, "beneficiaries": None, "district": "Pakur"}]
    r = field_scores(gold, pred, fields=("baseline", "target", "beneficiaries", "district"))
    # doc 1: baseline correct, target wrong, beneficiaries hallucinated, district correct (case-insensitive)
    # doc 2: baseline correct_null, target correct, beneficiaries missed, district correct
    assert r["counts"] == {"correct": 4, "wrong": 1, "missed": 1, "hallucinated": 1, "correct_null": 1}
    # hallucination: of the 2 fields the text did not state, 1 was filled in -> 0.5
    assert r["hallucination_rate"] == pytest.approx(0.5)
    # accuracy on stated fields: correct 4 of stated 6 (4 correct + 1 wrong + 1 missed)
    assert r["accuracy_on_stated"] == pytest.approx(4 / 6, abs=1e-4)
    assert r["per_field"]["beneficiaries"] == {"correct": 0, "wrong": 0, "missed": 1,
                                               "hallucinated": 1, "correct_null": 0}
