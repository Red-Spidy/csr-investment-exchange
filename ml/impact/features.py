"""Features for the impact model: only what is known when a proposal is scored.

Two rules keep the model honest:

* Nothing hidden, nothing from the future. No `hidden_*` column, no outcome.
* What a proposal does not state stays missing. If the baseline is not given,
  the claimed improvement is unknown, so `claim_rel` is NaN -- XGBoost learns
  what missing means instead of being fed a guess.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from synth.anchors import SECTORS
from synth.catalog import ADMIN_BUDGET_ITEM, SECTOR_PROFILE

METRICS = tuple(m.name for profile in SECTOR_PROFILE.values() for m in profile.metrics)
REFERENCE_YEAR = 2024
_NGO_COLUMNS = ["ngo_id", "established_year", "past_projects", "past_delivery_rate"]


def project_frame(projects: pd.DataFrame, ngos: pd.DataFrame,
                  ngo_scores: pd.DataFrame | None = None) -> pd.DataFrame:
    """Projects joined with what is known about their NGO, including the fraud
    model's score when available."""
    frame = projects.merge(ngos[_NGO_COLUMNS], on="ngo_id", how="left")
    if ngo_scores is None:
        frame["ngo_fraud_score"] = np.nan
    else:
        scores = ngo_scores[["ngo_id", "anomaly_score"]].rename(columns={"anomaly_score": "ngo_fraud_score"})
        frame = frame.merge(scores, on="ngo_id", how="left")
    return frame


def _admin_amount(lines) -> float:
    return float(sum(line["amount"] for line in lines if line["item"] == ADMIN_BUDGET_ITEM))


class ImpactFeatures:
    """Medians are training statistics, so one project scored later is
    compared with history rather than with itself."""

    def __init__(self) -> None:
        self.sector_cpb_median: dict[str, float] = {}
        self.global_cpb_median: float = float("nan")
        self.metric_claim_median: dict[str, float] = {}

    def fit(self, frame: pd.DataFrame) -> ImpactFeatures:
        ben = frame["states_beneficiaries"].astype(bool)
        cpb = frame["requested_amount"] / frame["beneficiaries"]
        self.sector_cpb_median = cpb[ben].groupby(frame.loc[ben, "sector"]).median().to_dict()
        self.global_cpb_median = float(cpb[ben].median())

        base = frame["states_baseline"].astype(bool)
        claim = (frame["target"] - frame["baseline"]).abs()
        # Claims are only comparable within a metric: 8 points is not 250 hectares.
        self.metric_claim_median = claim[base].groupby(frame.loc[base, "metric_name"]).median().to_dict()
        return self

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        f = frame.reset_index(drop=True)
        amount = f["requested_amount"].astype(float)
        ben = f["states_beneficiaries"].astype(bool).to_numpy()
        base = f["states_baseline"].astype(bool).to_numpy()
        breakdown = f["states_budget_breakdown"].astype(bool).to_numpy()

        cpb_median = f["sector"].map(self.sector_cpb_median).fillna(self.global_cpb_median)
        claim_median = f["metric_name"].map(self.metric_claim_median).astype(float)
        claim = (f["target"] - f["baseline"]).abs()
        admin = f["budget_lines"].apply(_admin_amount)

        return pd.DataFrame({
            "sector": pd.Categorical(f["sector"], categories=SECTORS),
            "metric": pd.Categorical(f["metric_name"], categories=METRICS),
            "log_amount": np.log(amount),
            "log_beneficiaries": np.where(ben, np.log(f["beneficiaries"].astype(float)), np.nan),
            "log_cpb_rel": np.where(ben, np.log(amount / f["beneficiaries"] / cpb_median), np.nan),
            "claim_rel": np.where(base, claim / claim_median, np.nan),
            "duration_months": f["duration_months"].astype(float),
            "ngo_years_active": (REFERENCE_YEAR - f["established_year"]).astype(float),
            "past_projects": f["past_projects"].astype(float),
            "past_delivery_rate": f["past_delivery_rate"].astype(float),
            "states_baseline": base.astype(float),
            "states_beneficiaries": ben.astype(float),
            "states_budget_breakdown": breakdown.astype(float),
            "admin_share": np.where(breakdown, admin / amount, np.nan),
            "ngo_fraud_score": f["ngo_fraud_score"].astype(float),
        })
