"""Train and evaluate the impact model.

    make train-impact   # -> ml/artifacts/impact_xgb.joblib, ml/results/impact_metrics.json

Needs the fraud model first (make train-fraud): the NGO's fraud score is one
of the impact features.

Protocol, so the test number means something:
  1. Choose tree depth and count on the VAL split (early stopping).
  2. Refit on TRAIN + VAL with those settings. This is the saved model.
  3. Score the TEST split once. Test NGOs were never seen in steps 1-2.

Reported alongside: a constant baseline (always predict the training mean),
an oracle fit on the hidden traits (the best any model could do), and an
ablation that drops everything known about the NGO.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score
from xgboost import XGBRegressor

from fraud.model import FraudModel, with_sector
from impact.features import project_frame
from impact.model import MODEL_VERSION, ImpactModel, _booster_params
from synth.build import load_world

DATASETS = Path("ml/datasets")
FRAUD_ARTIFACT = Path("ml/artifacts/fraud_iforest.joblib")
ARTIFACT = Path("ml/artifacts/impact_xgb.joblib")
RESULTS = Path("ml/results/impact_metrics.json")
DEPTHS = (2, 3, 4, 5)
NGO_FEATURE_SOURCES = ["established_year", "past_projects", "past_delivery_rate", "ngo_fraud_score"]
ORACLE_FEATURES = ["hidden_capacity", "hidden_is_fraudulent", "hidden_budget_adequacy", "hidden_ambition"]


def _score(y: np.ndarray, pred: pd.DataFrame | np.ndarray) -> dict:
    point = pred["fraction"].to_numpy() if isinstance(pred, pd.DataFrame) else pred
    out = {"mae": round(mean_absolute_error(y, point), 4), "r2": round(r2_score(y, point), 4)}
    if isinstance(pred, pd.DataFrame):
        lo, hi = pred["fraction_low"].to_numpy(), pred["fraction_high"].to_numpy()
        out["interval_coverage"] = round(float(((lo <= y) & (y <= hi)).mean()), 4)
        out["interval_width"] = round(float((hi - lo).mean()), 4)
    return out


def select_depth(train: pd.DataFrame, val: pd.DataFrame) -> tuple[int, int, dict]:
    """Best depth by validation MAE, with its early-stopped tree count."""
    results = {}
    for depth in DEPTHS:
        model = ImpactModel.fit(train, val, max_depth=depth)
        results[depth] = (_score(val["delivered_fraction"].to_numpy(), model.predict(val))["mae"],
                          model.params["n_estimators"])
    best = min(results, key=lambda d: results[d][0])
    return best, results[best][1], {str(d): {"val_mae": m, "n_estimators": n} for d, (m, n) in results.items()}


def _oracle(fit: pd.DataFrame, test: pd.DataFrame, depth: int, n: int) -> dict:
    cols = ["sector", *ORACLE_FEATURES]
    def X(f):
        x = f[cols].copy()
        x["sector"] = x["sector"].astype("category")
        x["hidden_is_fraudulent"] = x["hidden_is_fraudulent"].astype(float)
        return x
    model = XGBRegressor(n_estimators=n, **_booster_params(depth, 0)).fit(X(fit), fit["delivered_fraction"])
    return _score(test["delivered_fraction"].to_numpy(), np.clip(model.predict(X(test)), 0, 1))


def main() -> None:
    world = load_world(DATASETS)
    fraud = FraudModel.load(FRAUD_ARTIFACT)
    scores = fraud.score_ngos(with_sector(world.spending, world.ngos))
    frame = project_frame(world.projects, world.ngos, scores)
    frame = frame.merge(world.ngos[["ngo_id", "hidden_capacity", "hidden_is_fraudulent"]], on="ngo_id")

    train, val, test = (frame[frame["split"] == s] for s in ("train", "val", "test"))
    depth, n_trees, sweep = select_depth(train, val)

    fit_on = pd.concat([train, val], ignore_index=True)
    model = ImpactModel.fit(fit_on, max_depth=depth, n_estimators=n_trees)
    model.save(ARTIFACT)

    y = test["delivered_fraction"].to_numpy()
    full = _score(y, model.predict(test))
    constant = _score(y, np.full(len(y), fit_on["delivered_fraction"].mean()))
    oracle = _oracle(fit_on, test, depth, n_trees)

    blind = lambda f: f.assign(**{c: np.nan for c in NGO_FEATURE_SOURCES})
    proposal_only = _score(y, ImpactModel.fit(blind(fit_on), max_depth=depth, n_estimators=n_trees).predict(blind(test)))

    gain = model.point.get_booster().get_score(importance_type="gain")
    total = sum(gain.values())
    importance = {k: round(v / total, 4) for k, v in sorted(gain.items(), key=lambda kv: -kv[1])}

    examples = model.forecast(test.head(3)).merge(
        test[["project_id", "title", "baseline", "target", "achieved_delta", "delivered_fraction", "states_baseline"]],
        on="project_id")

    report = {
        "model_version": MODEL_VERSION,
        "protocol": "depth chosen on val by early stopping; refit on train+val; test scored once",
        "chosen": {"max_depth": depth, "n_estimators": n_trees},
        "depth_sweep": sweep,
        "test_n_projects": int(len(test)),
        "test": {"xgboost": full, "constant_baseline": constant, "oracle_hidden_traits": oracle,
                 "ablation_proposal_only": proposal_only},
        "feature_importance_gain": importance,
        "examples": examples.to_dict(orient="records"),
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, indent=2, default=str) + "\n")

    print(f"chosen depth {depth}, {n_trees} trees | test: {len(test)} projects from unseen NGOs")
    print(f"{'':26}{'MAE':>8}{'R2':>8}{'cover80':>9}{'width':>8}")
    for name, m in (("constant baseline", constant), ("proposal only", proposal_only),
                    ("xgboost (full)", full), ("oracle (hidden traits)", oracle)):
        print(f"{name:26}{m['mae']:>8}{m['r2']:>8}{m.get('interval_coverage', ''):>9}{m.get('interval_width', ''):>8}")
    print("top features:", ", ".join(f"{k} {v:.0%}" for k, v in list(importance.items())[:6]))
    for r in report["examples"]:
        # A fallback forecast is a 0-1 fraction, so compare it with the fraction delivered.
        actual = r["achieved_delta"] if r["states_baseline"] else r["delivered_fraction"]
        claim = f"claimed {r['baseline']}->{r['target']}" if r["states_baseline"] else "no baseline stated"
        print(f"  {r['title'][:52]:52} {claim:22} | forecast {r['predicted_value']:+.2f} "
              f"[{r['ci_low']:+.2f}, {r['ci_high']:+.2f}] {r['metric_unit']} | actual {actual:+.2f}")
    print(f"saved {ARTIFACT}, {RESULTS}")


if __name__ == "__main__":
    main()
