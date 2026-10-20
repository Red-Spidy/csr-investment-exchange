"""XGBoost impact model: as-stated features, intervals in proposal units,
persistence, and quality on NGOs it never saw."""

import math

import numpy as np
import pandas as pd
import pytest

from fraud.model import FraudModel, with_sector
from impact.features import ImpactFeatures, project_frame
from impact.model import ImpactModel, ordered_interval, to_units


def _project(**overrides):
    row = dict(
        project_id=1, ngo_id=1, sector="education", metric_name="attendance_rate",
        metric_unit="percentage_points", baseline=61.0, target=69.0, beneficiaries=1000,
        requested_amount=1_000_000, duration_months=12, num_phases=2,
        budget_lines=[{"item": "learning materials", "amount": 900_000},
                      {"item": "administration and monitoring", "amount": 100_000}],
        states_baseline=True, states_beneficiaries=True, states_budget_breakdown=True,
        established_year=2010, past_projects=4, past_delivery_rate=0.6, ngo_fraud_score=0.2,
    )
    row.update(overrides)
    return row


@pytest.fixture(scope="module")
def frame(world):
    spending = with_sector(world.spending, world.ngos)
    scores = FraudModel.fit(spending).score_ngos(spending)
    return project_frame(world.projects, world.ngos, scores)


@pytest.fixture(scope="module")
def trained(frame):
    return ImpactModel.fit(frame[frame["split"] == "train"], frame[frame["split"] == "val"])


def test_features_never_include_hidden_outcome_or_split_columns(frame):
    X = ImpactFeatures().fit(frame).transform(frame)
    forbidden = {"delivered_fraction", "achieved_delta", "split", "project_id", "ngo_id"}
    assert not forbidden & set(X.columns)
    assert not any(c.startswith("hidden_") for c in X.columns)


def test_values_a_proposal_did_not_state_are_missing_not_guessed():
    stated = pd.DataFrame([_project()])
    vague = pd.DataFrame([_project(states_baseline=False, states_beneficiaries=False,
                                   states_budget_breakdown=False)])
    f = ImpactFeatures().fit(stated)
    s, v = f.transform(stated).iloc[0], f.transform(vague).iloc[0]
    for col in ("claim_rel", "log_beneficiaries", "log_cpb_rel", "admin_share"):
        assert not math.isnan(s[col]), col
        assert math.isnan(v[col]), col


def test_cost_per_beneficiary_is_relative_to_the_training_sector_median():
    train = pd.DataFrame([_project(project_id=i, requested_amount=a, beneficiaries=1000)
                          for i, a in enumerate([300_000, 400_000, 500_000])])
    one = pd.DataFrame([_project(requested_amount=800_000, beneficiaries=1000)])
    # median training cost is Rs 400 per beneficiary; this one is Rs 800
    assert ImpactFeatures().fit(train).transform(one)["log_cpb_rel"].iloc[0] == pytest.approx(math.log(2))


def test_admin_share_is_read_from_the_budget_breakdown():
    X = ImpactFeatures().fit(pd.DataFrame([_project()])).transform(pd.DataFrame([_project()]))
    assert X["admin_share"].iloc[0] == pytest.approx(0.10)


def test_interval_always_contains_the_point_and_stays_in_zero_one():
    # Quantile models can cross; the DB's ci_ordered CHECK must still hold.
    assert ordered_interval(0.6, (0.7, 0.5, 0.3)) == pytest.approx((0.6, 0.3, 0.7))
    assert ordered_interval(0.95, (0.5, 0.7, 0.9)) == pytest.approx((0.95, 0.5, 0.95))
    assert ordered_interval(1.2, (0.8, 0.9, 1.1)) == pytest.approx((1.0, 0.8, 1.0))


def test_forecast_is_expressed_in_the_proposals_own_units():
    # +8 points claimed, 60% expected to be delivered, 80% interval 40-80%
    assert to_units(8.0, 0.6, 0.4, 0.8) == pytest.approx((4.8, 3.2, 6.4))
    # A claimed reduction (-6) flips the interval; bounds are ordered by value.
    assert to_units(-6.0, 0.6, 0.4, 0.8) == pytest.approx((-3.6, -4.8, -2.4))


def test_forecast_falls_back_to_the_fraction_when_no_claim_was_stated(trained, frame):
    row = frame[frame["split"] == "test"].head(1).copy()
    row["states_baseline"] = False
    out = trained.forecast(row).iloc[0]
    assert (out["metric_name"], out["metric_unit"]) == ("outcome_score", "normalised_0_1")
    assert out["predicted_value"] == pytest.approx(out["impact_norm"])
    assert out["ci_low"] <= out["predicted_value"] <= out["ci_high"]


def test_saved_model_predicts_identically(trained, frame, tmp_path):
    path = tmp_path / "impact.joblib"
    trained.save(path)
    pd.testing.assert_frame_equal(ImpactModel.load(path).forecast(frame), trained.forecast(frame))


def test_beats_the_constant_baseline_on_ngos_it_never_saw_with_honest_intervals(trained, frame):
    test = frame[frame["split"] == "test"]
    pred = trained.predict(test)
    y = test["delivered_fraction"].to_numpy()
    mae = np.abs(pred["fraction"] - y).mean()
    baseline_mae = np.abs(frame.loc[frame["split"] == "train", "delivered_fraction"].mean() - y).mean()
    assert mae < 0.95 * baseline_mae
    coverage = ((pred["fraction_low"] <= y) & (y <= pred["fraction_high"])).mean()
    assert 0.70 <= coverage <= 0.90       # nominal 80% interval
