"""XGBoost impact model: what fraction of a proposal's claim will be delivered,
with an 80% interval, expressed in the proposal's own units.

Two boosters share one feature set:
  * a point model (squared error) for the forecast itself
  * a quantile model (0.1 / 0.5 / 0.9) for the interval

The forecast for "+8 points of attendance" with 60% expected delivery is
"+4.8 points". The interval is what lets a reviewer tell a confident forecast
from a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from impact.features import ImpactFeatures

MODEL_VERSION = "xgb-v1"
QUANTILES = (0.1, 0.5, 0.9)
FALLBACK_METRIC = ("outcome_score", "normalised_0_1")
MAX_TREES = 2000
EARLY_STOPPING_ROUNDS = 50


def ordered_interval(point: float, quantiles) -> tuple[float, float, float]:
    """(point, low, high) with low <= point <= high, all in [0, 1]. Quantile
    models can cross, and the ci_ordered CHECK in the schema must still hold,
    so the interval is widened to contain the point rather than the point moved."""
    lo, _, hi = sorted(quantiles)
    point = float(np.clip(point, 0.0, 1.0))
    return point, float(np.clip(min(lo, point), 0.0, 1.0)), float(np.clip(max(hi, point), 0.0, 1.0))


def to_units(claimed_delta: float, point: float, lo: float, hi: float) -> tuple[float, float, float]:
    """Scale delivered fractions by the claim. A claimed reduction (negative
    delta) flips the interval, so bounds are ordered by value."""
    a, b = claimed_delta * lo, claimed_delta * hi
    return claimed_delta * point, min(a, b), max(a, b)


def _booster_params(max_depth: int, random_state: int) -> dict:
    return dict(
        max_depth=max_depth, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
        min_child_weight=5, tree_method="hist", enable_categorical=True, random_state=random_state,
    )


@dataclass
class ImpactModel:
    features: ImpactFeatures
    point: XGBRegressor
    quantile: XGBRegressor
    params: dict = field(default_factory=dict)

    @classmethod
    def fit(cls, train: pd.DataFrame, val: pd.DataFrame | None = None, max_depth: int = 3,
            n_estimators: int | None = None, random_state: int = 0) -> ImpactModel:
        """With `val` and no `n_estimators`, the tree count is chosen by early
        stopping on val; both boosters are then fit on `train` alone."""
        features = ImpactFeatures().fit(train)
        X, y = features.transform(train), train["delivered_fraction"].to_numpy()
        params = _booster_params(max_depth, random_state)

        if n_estimators is None:
            if val is None:
                raise ValueError("pass val for early stopping, or n_estimators")
            probe = XGBRegressor(n_estimators=MAX_TREES, early_stopping_rounds=EARLY_STOPPING_ROUNDS,
                                 eval_metric="mae", **params)
            probe.fit(X, y, eval_set=[(features.transform(val), val["delivered_fraction"].to_numpy())],
                      verbose=False)
            n_estimators = probe.best_iteration + 1

        point = XGBRegressor(n_estimators=n_estimators, **params).fit(X, y)
        quantile = XGBRegressor(n_estimators=n_estimators, objective="reg:quantileerror",
                                quantile_alpha=np.array(QUANTILES), **params).fit(X, y)
        return cls(features, point, quantile,
                   {"max_depth": max_depth, "n_estimators": n_estimators, **params})

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Delivered fraction with its 80% interval, per project."""
        X = self.features.transform(frame)
        rows = [ordered_interval(p, q) for p, q in zip(self.point.predict(X), self.quantile.predict(X))]
        out = pd.DataFrame(rows, columns=["fraction", "fraction_low", "fraction_high"])
        out.insert(0, "project_id", frame["project_id"].to_numpy())
        return out

    def forecast(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Rows shaped for the impact_predictions table."""
        pred = self.predict(frame)
        f = frame.reset_index(drop=True)
        rows = []
        for i, p in pred.iterrows():
            stated = bool(f.loc[i, "states_baseline"])
            delta = float(f.loc[i, "target"] - f.loc[i, "baseline"]) if stated else float("nan")
            if stated and delta != 0:
                name, unit = f.loc[i, "metric_name"], f.loc[i, "metric_unit"]
                value, low, high = to_units(delta, p["fraction"], p["fraction_low"], p["fraction_high"])
            else:
                # Nothing measurable was claimed: report the fraction itself
                # rather than invent a denominator.
                (name, unit), value, low, high = FALLBACK_METRIC, p["fraction"], p["fraction_low"], p["fraction_high"]
            rows.append({
                "project_id": p["project_id"],
                "metric_name": name,
                "metric_unit": unit,
                "predicted_value": round(value, 4),
                "ci_low": round(low, 4),
                "ci_high": round(high, 4),
                "impact_norm": round(p["fraction"], 4),
                "model_version": MODEL_VERSION,
            })
        return pd.DataFrame(rows)

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> ImpactModel:
        return joblib.load(path)
