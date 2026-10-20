"""Isolation Forest over NGO spending years, scored per NGO.

Isolation Forest learns what normal spending looks like and isolates what
does not fit; it never sees a fraud label. Labels are used only to evaluate.

The NGO's score is its most anomalous recent year, expressed as a percentile
against the training NGOs: 0.93 reads "more unusual than 93% of NGOs". The
top REVIEW_SHARE are flagged for human review. A flag routes a project to a
person; it never rejects one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from fraud.features import FraudFeatures

MODEL_VERSION = "iforest-v1"
N_TREES = 300
RECENT_YEARS = 3          # misuse that stopped five years ago is not today's risk
REVIEW_SHARE = 0.10       # flag the most anomalous 10% of NGOs; ~6% are fraudulent


def with_sector(spending: pd.DataFrame, ngos: pd.DataFrame) -> pd.DataFrame:
    """Spending rows carry no sector; the cost feature needs one."""
    return spending.merge(ngos[["ngo_id", "sector"]], on="ngo_id", how="left")


@dataclass
class FraudModel:
    features: FraudFeatures
    forest: IsolationForest
    reference: np.ndarray     # sorted raw NGO scores from training: the percentile scale

    @classmethod
    def fit(cls, spending: pd.DataFrame, random_state: int = 0,
            columns: list[str] | None = None) -> FraudModel:
        features = FraudFeatures(columns=columns).fit(spending)
        forest = IsolationForest(n_estimators=N_TREES, random_state=random_state)
        forest.fit(features.transform(spending))
        model = cls(features=features, forest=forest, reference=np.empty(0))
        model.reference = np.sort(model._raw_ngo_scores(spending)["raw"].to_numpy())
        return model

    def score_rows(self, spending: pd.DataFrame) -> np.ndarray:
        """Raw anomaly per NGO-year; higher is more unusual."""
        return -self.forest.score_samples(self.features.transform(spending))

    def _raw_ngo_scores(self, spending: pd.DataFrame) -> pd.DataFrame:
        s = spending.reset_index(drop=True)
        years = pd.DataFrame({"ngo_id": s["ngo_id"], "fy": s["fy"], "raw": self.score_rows(s)})
        recent = years.sort_values("fy").groupby("ngo_id").tail(RECENT_YEARS)
        return recent.groupby("ngo_id", as_index=False)["raw"].max()

    def score_ngos(self, spending: pd.DataFrame) -> pd.DataFrame:
        """One row per NGO: anomaly_score in [0, 1] and the review flag."""
        raw = self._raw_ngo_scores(spending)
        pct = np.searchsorted(self.reference, raw["raw"].to_numpy(), side="right") / len(self.reference)
        return pd.DataFrame({
            "ngo_id": raw["ngo_id"].to_numpy(),
            "anomaly_score": np.round(pct, 4),
            "is_anomaly": pct > 1 - REVIEW_SHARE,
        })

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> FraudModel:
        return joblib.load(path)
