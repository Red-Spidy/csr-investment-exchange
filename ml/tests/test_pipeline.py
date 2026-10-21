"""Mapping model outputs onto the database rows the API and SQL read."""

import json
import math

import pandas as pd

from nlp.decode import Field
from nlp.reader import Reading
from pipeline.score import (extraction_row, fraud_evidence, impact_frame, project_canonical_text,
                            rulebook_canonical_text)

TEXT = "Asha Trust will run remedial classes in Gaya. We aim to raise attendance from 48% to 57%."


def _reading(**overrides):
    at = lambda s: TEXT.index(s)
    fields = {"baseline": Field(48, "48", at("48"), at("48") + 2, 0.99),
              "target": Field(57, "57", at("57"), at("57") + 2, 0.98),
              "district": Field("Gaya", "Gaya", at("Gaya"), at("Gaya") + 4, 0.97)}
    base = dict(sdgs=[4], sdg_confidence={"4": 0.95}, metric_name="attendance_rate",
                metric_unit="percentage_points", metric_confidence=0.9, fields=fields,
                goal="We aim to raise attendance from 48% to 57%.",
                red_flags=["no beneficiary count stated"])
    base.update(overrides)
    return Reading(**base)


PROJECT = {"id": 7, "title": "Remedial classes, Gaya", "sector": "education", "state": "Bihar",
           "requested_amount": 900000, "duration_months": 12, "num_phases": 2}
NGO = {"id": 3, "established_year": 2010, "past_projects": 0, "past_delivery_rate": None}


def test_extraction_row_carries_what_bert_read_and_nothing_it_did_not():
    row = extraction_row(7, _reading(), "canonical", [0.1] * 384)
    assert json.loads(row["target_metric"]) == {"name": "attendance_rate", "unit": "percentage_points",
                                                "baseline": 48, "target": 57}
    assert row["beneficiaries"] is None                    # not stated -> not invented
    assert json.loads(row["geography"]) == {"district": "Gaya"}
    assert json.loads(row["goals"]) == ["We aim to raise attendance from 48% to 57%."]
    assert json.loads(row["red_flags"]) == ["no beneficiary count stated"]
    assert row["sdgs"] == [4] and json.loads(row["sdg_confidence"]) == {"4": 0.95}
    assert row["embedding"].startswith("[") and row["embedding"].count(",") == 383
    assert row["model_version"] == "bert-v1"


def test_impact_frame_states_a_claim_only_when_baseline_and_target_were_read():
    full = impact_frame(PROJECT, NGO, _reading(), fraud_score=0.3).iloc[0]
    assert bool(full["states_baseline"]) and (full["baseline"], full["target"]) == (48, 57)
    no_base = _reading(fields={k: v for k, v in _reading().fields.items() if k != "baseline"})
    vague = impact_frame(PROJECT, NGO, no_base, fraud_score=0.3).iloc[0]
    assert not bool(vague["states_baseline"]) and math.isnan(vague["baseline"])
    assert not bool(full["states_beneficiaries"]) and math.isnan(full["beneficiaries"])
    assert full["ngo_fraud_score"] == 0.3 and full["requested_amount"] == 900000


def test_metrics_that_start_from_nothing_need_only_a_target():
    at = TEXT.index("57")
    trees = _reading(metric_name="tree_cover", metric_unit="hectares",
                     fields={"target": Field(250, "250", at, at + 2, 0.9)})
    row = impact_frame(PROJECT | {"sector": "environment"}, NGO, trees, fraud_score=0.1).iloc[0]
    # "Add 250 hectares" is a claim of +250 from zero, so it can be forecast in hectares.
    assert bool(row["states_baseline"]) and (row["baseline"], row["target"]) == (0.0, 250)


def test_an_ngo_with_no_spending_history_gets_neutral_unflagged_evidence_and_a_red_flag():
    score, flagged, note = fraud_evidence(None, pd.DataFrame(), sector="education", ngo_id=3)
    assert (score, flagged) == (0.5, False) and "spending history" in note


def test_both_sides_of_a_match_are_described_in_the_same_vocabulary():
    project = project_canonical_text("Remedial classes, Gaya", "education", _reading(), "Bihar")
    rulebook = rulebook_canonical_text("Fund rural school attendance.", ["education"], ["Bihar"], [4])
    for text in (project, rulebook):
        assert "Quality Education" in text and "education" in text and "Bihar" in text
    assert "Gaya" in project
