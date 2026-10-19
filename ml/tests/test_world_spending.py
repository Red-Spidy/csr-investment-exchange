"""Spending table: one row per NGO per financial year, the Isolation Forest input.
Columns mirror ngo_spending_history in db/migrations/002_core_tables.sql."""

import pandas as pd

ALL_FYS = {"FY19-20", "FY20-21", "FY21-22", "FY22-23", "FY23-24"}
MANIPULABLE = ["admin_expense_ratio", "round_number_freq", "vendor_concentration", "report_latency_days"]


def _with_ngo(world) -> pd.DataFrame:
    cols = ["ngo_id", "sector", "established_year", "split", "hidden_is_fraudulent"]
    return world.spending.merge(world.ngos[cols], on="ngo_id", suffixes=("", "_ngo"))


def test_one_row_per_ngo_per_year_it_existed(world):
    s = _with_ngo(world)
    assert not s.duplicated(["ngo_id", "fy"]).any()      # UNIQUE (ngo_id, fy)
    assert set(s["fy"]) == ALL_FYS
    rows = s.groupby("ngo_id").size()
    established = world.ngos.set_index("ngo_id")["established_year"]
    # FY19-20 starts in 2019; an NGO founded in 2022 has FY22-23 and FY23-24 only.
    expected = 2024 - established.clip(lower=2019)
    assert (rows == expected.loc[rows.index]).all()
    assert set(rows.index) == set(world.ngos["ngo_id"])


def test_values_satisfy_db_check_constraints(world):
    s = world.spending
    assert (s["total_spend"] >= 0).all()
    for col in ("admin_expense_ratio", "round_number_freq", "vendor_concentration"):
        assert s[col].between(0, 1).all(), col
    for col in ("burn_rate_vs_schedule", "category_mix_drift"):
        assert s[col].abs().lt(100).all(), col          # NUMERIC(6,4)
    assert (s["report_latency_days"] >= 1).all()
    assert (s["cost_per_beneficiary"] > 0).all()


def test_spending_split_is_inherited_from_its_ngo(world):
    s = _with_ngo(world)
    assert (s["split"] == s["split_ngo"]).all()


def test_only_fraudulent_ngos_have_anomalous_years(world):
    s = _with_ngo(world)
    assert not s.loc[s["is_anomalous_truth"], "hidden_is_fraudulent"].eq(False).any()


def test_every_fraudulent_ngo_has_one_to_three_anomalous_years(world):
    s = _with_ngo(world)
    per_ngo = s[s["hidden_is_fraudulent"]].groupby("ngo_id")["is_anomalous_truth"].sum()
    assert len(per_ngo) == world.ngos["hidden_is_fraudulent"].sum()
    assert per_ngo.between(1, 3).all()


def test_anomalous_years_stand_out_on_manipulated_features(world):
    s = world.spending
    anomalous = s[s["is_anomalous_truth"]]
    normal = s[s["hidden_anomaly_kind"] == "none"]
    for col in MANIPULABLE:
        assert anomalous[col].mean() > 1.3 * normal[col].mean(), col


def test_some_fraud_is_subtle(world):
    # Each fraud year manipulates only a few features, so many anomalous rows
    # look normal on any single one. All-features-at-once would make
    # detection trivial and the evaluation meaningless.
    s = world.spending
    normal_p90 = s.loc[s["hidden_anomaly_kind"] == "none", "admin_expense_ratio"].quantile(0.9)
    anomalous = s[s["is_anomalous_truth"]]
    assert (anomalous["admin_expense_ratio"] <= normal_p90).mean() >= 0.2


def test_honest_ngos_have_legitimate_spikes_that_are_not_fraud(world):
    s = world.spending
    spikes = s[s["hidden_anomaly_kind"] == "legit_spike"]
    normal = s[s["hidden_anomaly_kind"] == "none"]
    assert len(spikes) > 0
    assert not spikes["is_anomalous_truth"].any()
    # A one-off big grant inflates spend and pace, not the fraud markers.
    assert spikes["total_spend"].median() > 1.5 * normal["total_spend"].median()
    assert abs(spikes["round_number_freq"].mean() - normal["round_number_freq"].mean()) < 0.03
    assert abs(spikes["vendor_concentration"].mean() - normal["vendor_concentration"].mean()) < 0.04


def test_cost_per_beneficiary_follows_sector_norms(world):
    s = _with_ngo(world)
    median = s[~s["is_anomalous_truth"]].groupby("sector")["cost_per_beneficiary"].median()
    # Norms: livelihood ~Rs 2,500, water ~Rs 70 per beneficiary.
    assert median["livelihood"] > 1500
    assert median["water_sanitation"] < 200
    assert median["livelihood"] > median["healthcare"] > median["water_sanitation"]


def test_fraud_stays_within_plausible_values(world):
    # A 60% admin ratio or 90% round-number invoices is a cartoon, not fraud
    # an auditor would plausibly miss. Real misuse hides inside believable values.
    a = world.spending[world.spending["is_anomalous_truth"]]
    assert a["admin_expense_ratio"].max() <= 0.45
    assert a["round_number_freq"].max() <= 0.75
    assert a["report_latency_days"].max() <= 120


def test_some_fraud_years_touch_a_single_feature(world):
    # The hardest fraud to catch moves one marker only. Measured against the
    # NGO's own normal years, so no hidden column is needed.
    s = world.spending
    normal = s[s["hidden_anomaly_kind"] == "none"]
    cols = ["admin_expense_ratio", "round_number_freq", "vendor_concentration",
            "burn_rate_vs_schedule", "category_mix_drift"]
    upper = normal.groupby("ngo_id")[cols].max()
    a = s[s["is_anomalous_truth"]].set_index("ngo_id")[cols]
    exceeded = (a > upper.reindex(a.index) + 0.05).sum(axis=1)
    assert (exceeded <= 1).mean() >= 0.25


def test_enough_fraud_years_for_grouped_cross_validation(world):
    # The test split alone holds only ~5 fraud NGOs, so the fraud model is
    # evaluated with grouped CV over all NGOs. That needs enough positives.
    assert world.spending["is_anomalous_truth"].sum() >= 50
