"""Train and evaluate the fraud model.

    make train-fraud   # -> ml/artifacts/fraud_iforest.joblib, ml/results/fraud_metrics.json

Evaluation is stratified, grouped cross-validation over NGOs: every NGO is
scored by a model fit only on other NGOs' spending, and every fold holds its
share of fraudulent NGOs. Headline numbers are per NGO, because a project's
fraud score is its NGO's score.

The deployed model is then fit on every NGO's spending. That is sound here
and only here: Isolation Forest never sees a label, so no label leaks into
training. The labels are used for evaluation alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold

from fraud.features import MARKERS
from fraud.model import MODEL_VERSION, REVIEW_SHARE, FraudModel, with_sector
from synth.build import load_world

DATASETS = Path("ml/datasets")
ARTIFACT = Path("ml/artifacts/fraud_iforest.joblib")
RESULTS = Path("ml/results/fraud_metrics.json")


def cross_validate(spending: pd.DataFrame, ngos: pd.DataFrame, n_splits: int = 5,
                   columns: list[str] | None = None, random_state: int = 0):
    """Out-of-fold NGO scores and NGO-level metrics."""
    s = with_sector(spending, ngos)
    truth = ngos.set_index("ngo_id")["hidden_is_fraudulent"]
    folds = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=random_state)

    parts = []
    for fold, (train_idx, test_idx) in enumerate(folds.split(s, s["ngo_id"].map(truth), groups=s["ngo_id"])):
        model = FraudModel.fit(s.iloc[train_idx], random_state=random_state, columns=columns)
        scored = model.score_ngos(s.iloc[test_idx])
        scored["fold"] = fold
        parts.append(scored)
    oof = pd.concat(parts, ignore_index=True)

    y = oof["ngo_id"].map(truth).astype(bool)
    flagged = oof["is_anomaly"]
    caught = int((flagged & y).sum())
    metrics = {
        "n_ngos": len(oof),
        "n_fraudulent": int(y.sum()),
        "ngo_roc_auc": round(roc_auc_score(y, oof["anomaly_score"]), 4),
        "ngo_avg_precision": round(average_precision_score(y, oof["anomaly_score"]), 4),
        "random_avg_precision": round(float(y.mean()), 4),
        "flagged_share": round(float(flagged.mean()), 4),
        "flagged_fraudulent": caught,
        "precision_at_flag": round(caught / max(int(flagged.sum()), 1), 4),
        "recall_at_flag": round(caught / int(y.sum()), 4),
    }
    return oof, metrics


def main() -> None:
    world = load_world(DATASETS)
    _, full = cross_validate(world.spending, world.ngos)
    _, raw_only = cross_validate(world.spending, world.ngos, columns=MARKERS)

    model = FraudModel.fit(with_sector(world.spending, world.ngos))
    model.save(ARTIFACT)

    report = {
        "model_version": MODEL_VERSION,
        "evaluation": "stratified grouped 5-fold CV over NGOs, NGO-level",
        "review_share": REVIEW_SHARE,
        "with_ngo_relative_features": full,
        "ablation_raw_markers_only": raw_only,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, indent=2) + "\n")

    print(f"{'':32}{'full':>10}{'raw only':>10}")
    for key in ("ngo_roc_auc", "ngo_avg_precision", "precision_at_flag", "recall_at_flag", "flagged_fraudulent"):
        print(f"{key:32}{full[key]:>10}{raw_only[key]:>10}")
    print(f"random avg precision {full['random_avg_precision']} | {full['n_fraudulent']} fraudulent of {full['n_ngos']} NGOs")
    print(f"saved {ARTIFACT}, {RESULTS}")


if __name__ == "__main__":
    main()
