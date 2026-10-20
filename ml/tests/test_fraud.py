"""Isolation Forest fraud model: features, scoring, persistence, and quality on
NGOs it never saw."""

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score

from fraud.features import FraudFeatures
from fraud.model import FraudModel, with_sector


def _row(ngo_id, fy, sector="education", **overrides):
    row = dict(
        ngo_id=ngo_id, fy=fy, sector=sector, total_spend=2_000_000.0,
        admin_expense_ratio=0.10, burn_rate_vs_schedule=1.0, category_mix_drift=0.05,
        round_number_freq=0.14, vendor_concentration=0.27, report_latency_days=10,
        cost_per_beneficiary=450.0,
    )
    row.update(overrides)
    return row


@pytest.fixture(scope="module")
def trained(world):
    spending = with_sector(world.spending, world.ngos)
    return FraudModel.fit(spending[spending["split"] == "train"])


def test_each_year_is_compared_with_the_ngos_other_years():
    rows = pd.DataFrame([
        _row(1, "FY21-22", admin_expense_ratio=0.10),
        _row(1, "FY22-23", admin_expense_ratio=0.10),
        _row(1, "FY23-24", admin_expense_ratio=0.30),
    ])
    X = FraudFeatures().fit(rows).transform(rows)
    # FY23-24: 0.30 - median(0.10, 0.10) = 0.20
    # FY21-22: 0.10 - median(0.10, 0.30) = -0.10
    assert X["dev_admin_expense_ratio"].tolist() == pytest.approx([-0.10, -0.10, 0.20])


def test_cost_per_beneficiary_is_relative_to_the_training_sector_median():
    train = pd.DataFrame([_row(i, "FY23-24", cost_per_beneficiary=c) for i, c in enumerate([100.0, 200.0, 300.0])])
    one = pd.DataFrame([_row(99, "FY23-24", cost_per_beneficiary=400.0)])
    # Recomputing the median on the scoring data would make any single
    # project look exactly average.
    X = FraudFeatures().fit(train).transform(one)
    assert X["log_cpb_rel"].iloc[0] == pytest.approx(np.log(2.0))


def test_features_never_include_labels_or_hidden_columns(world):
    spending = with_sector(world.spending, world.ngos)
    X = FraudFeatures().fit(spending).transform(spending)
    leaked = {"is_anomalous_truth", "hidden_anomaly_kind", "split", "ngo_id", "fy", "sector"} & set(X.columns)
    assert not leaked
    assert not any(c.startswith("hidden_") for c in X.columns)


def test_scores_are_percentiles_between_zero_and_one(trained, world):
    spending = with_sector(world.spending, world.ngos)
    scores = trained.score_ngos(spending[spending["split"] != "train"])
    assert scores["anomaly_score"].between(0, 1).all()
    assert scores["ngo_id"].is_unique


def test_a_planted_outlier_ngo_is_flagged_and_a_normal_one_is_not(trained):
    years = ["FY21-22", "FY22-23", "FY23-24"]
    rows = [_row(9001, fy) for fy in years]
    rows += [_row(9002, fy) for fy in years[:2]]
    rows.append(_row(9002, "FY23-24", admin_expense_ratio=0.40, round_number_freq=0.70,
                     vendor_concentration=0.90, report_latency_days=90))
    scores = trained.score_ngos(pd.DataFrame(rows)).set_index("ngo_id")
    assert scores.loc[9002, "anomaly_score"] > scores.loc[9001, "anomaly_score"]
    assert bool(scores.loc[9002, "is_anomaly"])
    assert not bool(scores.loc[9001, "is_anomaly"])


def test_only_the_three_most_recent_years_count(trained):
    years = ["FY19-20", "FY20-21", "FY21-22", "FY22-23", "FY23-24"]
    clean = [_row(9003, fy) for fy in years]
    old_outlier = [_row(9004, fy) for fy in years[1:]]
    old_outlier.insert(0, _row(9004, "FY19-20", admin_expense_ratio=0.40, round_number_freq=0.70))
    scores = trained.score_ngos(pd.DataFrame(clean + old_outlier)).set_index("ngo_id")
    assert scores.loc[9004, "anomaly_score"] == scores.loc[9003, "anomaly_score"]


def test_saved_model_scores_identically(trained, world, tmp_path):
    spending = with_sector(world.spending, world.ngos)
    path = tmp_path / "fraud.joblib"
    trained.save(path)
    pd.testing.assert_frame_equal(FraudModel.load(path).score_ngos(spending), trained.score_ngos(spending))


def test_ranks_fraudulent_ngos_it_never_saw_above_honest_ones(trained, world):
    spending = with_sector(world.spending, world.ngos)
    held_out = spending[spending["split"] != "train"]
    scores = trained.score_ngos(held_out).merge(world.ngos[["ngo_id", "hidden_is_fraudulent"]], on="ngo_id")
    assert roc_auc_score(scores["hidden_is_fraudulent"], scores["anomaly_score"]) >= 0.8


def test_cross_validation_scores_every_ngo_once_from_a_model_that_never_saw_it():
    from fraud.train import cross_validate
    from synth.world import generate_world

    small = generate_world(seed=5, n_ngos=120, n_projects=10)
    oof, metrics = cross_validate(small.spending, small.ngos, n_splits=4)
    # Splitting rows instead of NGOs would put one NGO's years in several
    # folds and score it more than once -- with a model trained on its own years.
    assert oof["ngo_id"].is_unique
    assert set(oof["ngo_id"]) == set(small.ngos["ngo_id"])
    assert 0.0 <= metrics["ngo_avg_precision"] <= 1.0


def test_features_can_be_restricted_to_a_column_subset():
    rows = pd.DataFrame([_row(1, "FY22-23"), _row(1, "FY23-24", admin_expense_ratio=0.3)])
    X = FraudFeatures(columns=["admin_expense_ratio", "log_latency"]).fit(rows).transform(rows)
    assert list(X.columns) == ["admin_expense_ratio", "log_latency"]
