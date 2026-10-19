"""Project table: facts a proposal states, hidden drivers, and the outcome."""

import numpy as np
import pandas as pd


def _with_ngo(world) -> pd.DataFrame:
    ngo_cols = ["ngo_id", "sector", "split", "hidden_capacity", "hidden_is_fraudulent"]
    return world.projects.merge(world.ngos[ngo_cols], on="ngo_id", suffixes=("", "_ngo"))


def test_projects_belong_to_known_ngos_in_the_ngo_sector(world):
    p = _with_ngo(world)
    assert len(world.projects) == 2000
    assert world.projects["project_id"].is_unique
    assert len(p) == len(world.projects), "project references an unknown NGO"
    assert (p["sector"] == p["sector_ngo"]).all()


def test_project_split_is_inherited_from_its_ngo(world):
    # A per-project split would put one NGO in train and test: leakage.
    p = _with_ngo(world)
    assert (p["split"] == p["split_ngo"]).all()


def test_outcomes_match_the_ieg_calibration(world):
    f = world.projects["delivered_fraction"]
    assert f.between(0, 1).all()
    assert 0.58 <= f.mean() <= 0.66      # IEG mean 0.616
    assert 0.20 <= f.std() <= 0.28       # IEG SD 0.243


def test_sector_explains_only_a_few_percent_of_outcome_variance(world):
    p = world.projects
    f = p["delivered_fraction"]
    sector_means = p.groupby("sector")["delivered_fraction"].transform("mean")
    eta_squared = ((sector_means - f.mean()) ** 2).sum() / ((f - f.mean()) ** 2).sum()
    assert eta_squared < 0.05
    # IEG ordering survives: education delivers more than healthcare.
    by_sector = p.groupby("sector")["delivered_fraction"].mean()
    assert by_sector["education"] > by_sector["healthcare"]


def test_outcomes_rise_with_hidden_capacity(world):
    p = _with_ngo(world)
    assert p["hidden_capacity"].corr(p["delivered_fraction"]) > 0.2


def test_fraudulent_ngos_deliver_less(world):
    p = _with_ngo(world)
    by_fraud = p.groupby("hidden_is_fraudulent")["delivered_fraction"].mean()
    assert by_fraud[False] - by_fraud[True] >= 0.12


def test_underfunded_projects_deliver_less(world):
    p = world.projects
    low = p["hidden_budget_adequacy"] <= p["hidden_budget_adequacy"].quantile(0.25)
    high = p["hidden_budget_adequacy"] >= p["hidden_budget_adequacy"].median()
    assert p.loc[high, "delivered_fraction"].mean() - p.loc[low, "delivered_fraction"].mean() >= 0.03


def test_overambitious_claims_deliver_less(world):
    p = world.projects
    bold = p["hidden_ambition"] >= p["hidden_ambition"].quantile(0.75)
    modest = p["hidden_ambition"] <= p["hidden_ambition"].quantile(0.25)
    assert p.loc[modest, "delivered_fraction"].mean() - p.loc[bold, "delivered_fraction"].mean() >= 0.02


def test_claimed_target_moves_in_the_metric_direction(world):
    p = world.projects
    up = p["metric_direction"] == "increase"
    down = p["metric_direction"] == "decrease"
    assert up.any() and down.any()
    assert (p.loc[up, "target"] > p.loc[up, "baseline"]).all()
    assert (p.loc[down, "target"] < p.loc[down, "baseline"]).all()
    assert (p["target"] >= 0).all()
    pct = p["metric_unit"].isin(["percentage_points", "percent"])
    assert (p.loc[pct, "target"] <= 100).all()


def test_achieved_delta_is_claimed_delta_scaled_by_delivery(world):
    p = world.projects
    expected = (p["target"] - p["baseline"]) * p["delivered_fraction"]
    assert np.allclose(p["achieved_delta"], expected, atol=1e-3)


def test_budget_lines_sum_exactly_to_a_round_requested_amount(world):
    p = world.projects
    assert (p["requested_amount"] % 10_000 == 0).all()
    assert p["requested_amount"].between(300_000, 50_000_000).all()
    totals = p["budget_lines"].apply(lambda lines: sum(line["amount"] for line in lines))
    assert (totals == p["requested_amount"]).all()
    assert p["budget_lines"].apply(lambda lines: 3 <= len(lines) <= 5).all()


def test_project_fields_satisfy_db_constraints(world):
    p = world.projects
    assert (p["duration_months"] > 0).all()
    assert p["num_phases"].between(1, 12).all()
    assert p["sdgs"].apply(lambda s: len(s) > 0 and all(1 <= n <= 17 for n in s)).all()
    assert p["sdgs"].apply(lambda s: s == sorted(set(s))).all()


def test_sdgs_come_from_the_activities_described(world):
    p = world.projects
    meals = p[p["activities"].apply(lambda a: "midday meal support" in a)]
    saplings = p[p["activities"].apply(lambda a: "native sapling plantation" in a)]
    assert len(meals) > 0 and len(saplings) > 0
    assert meals["sdgs"].apply(lambda s: {2, 4} <= set(s)).all()
    assert saplings["sdgs"].apply(lambda s: {13, 15} <= set(s)).all()


def test_fraudulent_ngos_request_inflated_budgets(world):
    # Padding is the observable trace of fraud in a proposal: a high cost per
    # beneficiary for the sector.
    p = _with_ngo(world)
    cpb = p["requested_amount"] / p["beneficiaries"]
    relative = cpb / cpb.groupby(p["sector"]).transform("median")
    by_fraud = relative.groupby(p["hidden_is_fraudulent"]).median()
    assert by_fraud[True] >= 1.2 * by_fraud[False]


def test_weaker_ngos_write_vaguer_proposals(world):
    p = _with_ngo(world)
    weak = p["hidden_capacity"] <= p["hidden_capacity"].quantile(0.25)
    strong = p["hidden_capacity"] >= p["hidden_capacity"].quantile(0.75)
    assert p.loc[strong, "states_baseline"].mean() - p.loc[weak, "states_baseline"].mean() >= 0.10
