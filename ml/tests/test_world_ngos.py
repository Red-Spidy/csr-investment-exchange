"""NGO table: hidden traits, observable track record, and the train/val/test split."""

import numpy as np
import pandas as pd

from synth.world import generate_world


def test_same_seed_reproduces_identical_world():
    a = generate_world(seed=11, n_ngos=40, n_projects=120)
    b = generate_world(seed=11, n_ngos=40, n_projects=120)
    pd.testing.assert_frame_equal(a.ngos, b.ngos)
    pd.testing.assert_frame_equal(a.projects, b.projects)
    pd.testing.assert_frame_equal(a.spending, b.spending)


def test_different_seed_gives_different_world():
    a = generate_world(seed=11, n_ngos=40, n_projects=120)
    b = generate_world(seed=12, n_ngos=40, n_projects=120)
    assert not np.allclose(a.ngos["hidden_capacity"], b.ngos["hidden_capacity"])


def test_ngo_sectors_follow_csr_spend_shares(world):
    # Hand-normalised from RED Lab FY24 shares (education 33, healthcare 23,
    # livelihood 6 + rural development 17, environment 7) plus water and
    # sanitation 5.5 from the National CSR Portal; total 91.5.
    expected = {
        "education": 33 / 91.5,
        "healthcare": 23 / 91.5,
        "livelihood": 23 / 91.5,
        "environment": 7 / 91.5,
        "water_sanitation": 5.5 / 91.5,
    }
    counts = world.ngos["sector"].value_counts()
    n = len(world.ngos)
    assert set(counts.index) == set(expected)
    for sector, share in expected.items():
        assert abs(counts[sector] - share * n) <= 1, sector


def test_fraud_prevalence_is_about_six_percent(world):
    rate = world.ngos["hidden_is_fraudulent"].mean()
    assert 0.04 <= rate <= 0.08


def test_track_record_is_a_noisy_proxy_for_hidden_capacity(world):
    known = world.ngos[world.ngos["past_projects"] > 0]
    corr = known["past_delivery_rate"].corr(known["hidden_capacity"])
    # Above 0.95 means capacity leaked straight through; below 0.3 means the
    # track record carries no signal for the impact model to learn from.
    assert 0.3 < corr < 0.95


def test_new_ngos_have_no_track_record(world):
    ngos = world.ngos
    no_history = ngos["past_projects"] == 0
    assert no_history.any(), "expected some NGOs with no completed projects"
    assert ngos.loc[no_history, "past_delivery_rate"].isna().all()
    assert ngos.loc[~no_history, "past_delivery_rate"].notna().all()


def test_split_is_70_15_15_by_ngo_with_fraud_in_every_split(world):
    ngos = world.ngos
    shares = ngos["split"].value_counts(normalize=True)
    assert abs(shares["train"] - 0.70) <= 0.03
    assert abs(shares["val"] - 0.15) <= 0.03
    assert abs(shares["test"] - 0.15) <= 0.03
    fraud_per_split = ngos[ngos["hidden_is_fraudulent"]].groupby("split").size()
    for split in ("train", "val", "test"):
        assert fraud_per_split.get(split, 0) >= 2, split


def test_registration_numbers_are_unique(world):
    # ngos.registration_no is UNIQUE in the schema; a collision fails the load.
    assert world.ngos["registration_no"].is_unique
