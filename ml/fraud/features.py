"""Features for the fraud model.

Each NGO-year is described twice: on its own terms (an admin ratio of 0.30 is
high for anyone), and against the same NGO's other years (0.30 from an NGO
that always runs at 0.10 is a break in pattern). The second view is what
separates a fraudulent year from an NGO that is simply expensive to run.

Total spend is deliberately not a feature: a one-off large grant inflates it
in honest NGOs, and it is not a marker any of the fraud patterns move.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MARKERS = [
    "admin_expense_ratio",
    "round_number_freq",
    "vendor_concentration",
    "burn_rate_vs_schedule",
    "category_mix_drift",
    "log_latency",
    "log_cpb_rel",
]


def _deviation_from_other_years(values: pd.Series) -> pd.Series:
    """Each value minus the median of the same NGO's OTHER years. Leaving the
    year itself out stops a fraudulent year from diluting its own baseline."""
    v = values.to_numpy(dtype=float)
    if len(v) == 1:
        return pd.Series(0.0, index=values.index)
    others = [np.median(np.delete(v, i)) for i in range(len(v))]
    return pd.Series(v - np.array(others), index=values.index)


class FraudFeatures:
    """Fitted on training data only: the sector cost medians are training
    statistics, so a single project scored later is compared with history,
    not with itself."""

    def __init__(self, columns: list[str] | None = None) -> None:
        self.columns = columns          # None = every feature; a subset for ablations
        self.sector_cpb_median: dict[str, float] = {}
        self.global_cpb_median: float = float("nan")

    def fit(self, spending: pd.DataFrame) -> FraudFeatures:
        self.sector_cpb_median = spending.groupby("sector")["cost_per_beneficiary"].median().to_dict()
        self.global_cpb_median = float(spending["cost_per_beneficiary"].median())
        return self

    def transform(self, spending: pd.DataFrame) -> pd.DataFrame:
        s = spending.reset_index(drop=True)
        median = s["sector"].map(self.sector_cpb_median).fillna(self.global_cpb_median)
        base = pd.DataFrame({
            "admin_expense_ratio": s["admin_expense_ratio"].astype(float),
            "round_number_freq": s["round_number_freq"].astype(float),
            "vendor_concentration": s["vendor_concentration"].astype(float),
            "burn_rate_vs_schedule": s["burn_rate_vs_schedule"].astype(float),
            "category_mix_drift": s["category_mix_drift"].astype(float),
            "log_latency": np.log(s["report_latency_days"].astype(float)),
            "log_cpb_rel": np.log(s["cost_per_beneficiary"].astype(float) / median),
        })
        deviations = base.groupby(s["ngo_id"]).transform(_deviation_from_other_years)
        X = pd.concat([base, deviations.add_prefix("dev_")], axis=1)
        return X if self.columns is None else X[self.columns]
