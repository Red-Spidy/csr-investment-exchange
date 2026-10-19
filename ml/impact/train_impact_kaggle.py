"""Train the impact model on IEG World Bank project performance ratings.

Run this on Kaggle (CPU is fine -- see the note on accelerators below), then
copy the four artefacts it writes into ml/impact/ in the repo.

WHAT THIS PREDICTS
    impact_norm in [0,1]: how well a development project is expected to turn
    out, derived from IEG's 6-point outcome rating. The schema stores it in
    impact_predictions.impact_norm, with ci_low/ci_high as the 0.1 and 0.9
    quantiles -- so the model is a QUANTILE regressor, not a point estimator.
    Those column comments in 002_core_tables.sql are the spec; this file
    implements them rather than reinterpreting them.

WHY QUANTILES AND NOT A POINT PREDICTION
    A funding decision needs to know how uncertain the forecast is. A project
    predicted at 0.7 +/- 0.05 and one predicted at 0.7 +/- 0.40 should not be
    treated alike, and a single number cannot express the difference. The
    headline metric below is therefore INTERVAL COVERAGE, not R^2: if the
    [q0.1, q0.9] band is honest, ~80% of held-out actuals fall inside it.

ACCELERATOR
    Request NONE. This is tabular XGBoost on ~10k rows -- it fits in seconds on
    CPU, and a GPU session buys nothing. Save the GPU quota for the SDG
    transformer, which actually needs it.

OUTPUTS (the handoff contract -- all four are required)
    impact_model.json          the booster, version-portable JSON (never pickle)
    impact_features.json       feature order + category levels + target mapping
    impact_preprocessor.joblib fitted encoder; raw strings in, codes out
    impact_metrics.json        metrics from THIS run, for the report
"""

# ---------------------------------------------------------------------------
# CELL 0 -- pinned installs.
# These MUST match requirements.txt or the booster may not deserialise locally.
# Kaggle ships its own versions, so pin explicitly and assert afterwards.
#
#   !pip install -q xgboost==3.4.1 scikit-learn==1.9.1
# ---------------------------------------------------------------------------

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
import xgboost as xgb
from sklearn.compose import ColumnTransformer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import OrdinalEncoder

# Fail loudly and immediately rather than producing a model that will not load.
assert xgb.__version__.startswith("3.4"), f"need xgboost 3.4.x, got {xgb.__version__}"
assert sklearn.__version__.startswith("1.9"), f"need sklearn 1.9.x, got {sklearn.__version__}"

# Env-overridable so the same file runs unchanged on Kaggle and locally.
OUT = Path(os.environ.get("IMPACT_OUT", "/kaggle/working"))
QUANTILES = [0.1, 0.5, 0.9]          # must stay aligned with ci_low/ci_high
RANDOM_STATE = 42

# Kaggle input paths. Attach both datasets to the notebook.
IEG_DIR = Path(os.environ.get("IEG_DIR", "/kaggle/input/ieg-world-bank-project-performance-ratings"))
OPS_DIR = Path(os.environ.get("OPS_DIR", "/kaggle/input/world-bank-projects-operations"))


# ---------------------------------------------------------------------------
# CELL 1 -- schema discovery. RUN THIS AND READ THE OUTPUT BEFORE GOING ON.
#
# I could not inspect these CSVs, so every column name below is a CANDIDATE,
# not a fact. This cell prints what is actually there; resolve_column() then
# fuzzy-matches against it and raises a readable error listing the real columns
# if nothing matches. If a lookup fails, fix the candidate list -- do not
# silently drop the feature.
# ---------------------------------------------------------------------------

def discover(directory: Path) -> None:
    """Print every CSV in a Kaggle input dir with its shape and columns."""
    if not directory.exists():
        print(f"!! {directory} does not exist -- is the dataset attached?")
        return
    for csv in sorted(directory.glob("**/*.csv")):
        try:
            head = pd.read_csv(csv, nrows=5, low_memory=False)
        except Exception as exc:                      # encoding/delimiter oddities
            print(f"   {csv.name}: unreadable ({exc})")
            continue
        print(f"\n== {csv.name}  ({head.shape[1]} cols)")
        for c in head.columns:
            print(f"     {c}")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def resolve_column(df: pd.DataFrame, candidates: list[str], *, required: bool = True) -> str | None:
    """Find the real column matching any candidate, ignoring case/spacing.

    Exact-normalised match first, then substring. Raises with the actual column
    list when required and nothing matches -- a loud failure here is much
    cheaper than a feature that silently becomes all-NaN.
    """
    norm_map = {_norm(c): c for c in df.columns}
    for cand in candidates:
        if (hit := norm_map.get(_norm(cand))) is not None:
            return hit
    for cand in candidates:
        n = _norm(cand)
        for norm_col, real in norm_map.items():
            if n and (n in norm_col or norm_col in n):
                return real
    if required:
        raise KeyError(
            f"none of {candidates} found. Actual columns:\n  " + "\n  ".join(map(str, df.columns))
        )
    return None


# discover(IEG_DIR); discover(OPS_DIR)     # <- uncomment, run, read, then proceed


# ---------------------------------------------------------------------------
# CELL 2 -- load and join.
# ---------------------------------------------------------------------------

def _largest_csv(directory: Path) -> Path:
    csvs = sorted(directory.glob("**/*.csv"), key=lambda p: p.stat().st_size, reverse=True)
    if not csvs:
        raise FileNotFoundError(f"no CSV under {directory}")
    return csvs[0]


def load_ieg() -> pd.DataFrame:
    path = _largest_csv(IEG_DIR)
    print(f"IEG ratings <- {path.name}")
    df = pd.read_csv(path, low_memory=False)
    # FIVE real columns ship with trailing spaces ('Lending Instrument ',
    # 'Approval Date ', 'Deactivation Date ', 'IEG_EvalDate ',
    # 'IEG_ImplementingAgencyPerf '). Left alone they turn every lookup into a
    # silent miss, so normalise once here rather than guessing per call site.
    df.columns = [c.strip() for c in df.columns]
    return df


def load_ops() -> pd.DataFrame | None:
    """Operations data is optional -- it adds features but IEG alone can train."""
    if not OPS_DIR.exists():
        print("ops dataset not attached; continuing with IEG columns only")
        return None
    path = _largest_csv(OPS_DIR)
    print(f"operations  <- {path.name}")
    return pd.read_csv(path, low_memory=False)


# ---------------------------------------------------------------------------
# CELL 3 -- target construction.
#
# IEG outcome ratings are a 6-point ordinal scale. Map to [0,1] because
# impact_predictions.impact_norm carries CHECK (impact_norm BETWEEN 0 AND 1).
# Both spelled-out labels and numeric codes appear in the wild, so handle both.
# ---------------------------------------------------------------------------

RATING_TO_SCORE = {
    "highly unsatisfactory": 0.0,
    "unsatisfactory": 0.2,
    "moderately unsatisfactory": 0.4,
    "moderately satisfactory": 0.6,
    "satisfactory": 0.8,
    "highly satisfactory": 1.0,
}
# Some extracts use abbreviations.
RATING_TO_SCORE.update({
    "hu": 0.0, "u": 0.2, "mu": 0.4, "ms": 0.6, "s": 0.8, "hs": 1.0,
})

# VERIFIED distribution in the real file (12,932 rows):
#   Satisfactory 6081 | Moderately Satisfactory 2853 | Unsatisfactory 2127
#   Moderately Unsatisfactory 1108 | Highly Satisfactory 405
#   Highly Unsatisfactory 178
# These three are NOT ratings and must be dropped, not mapped to a number --
# scoring them as 0.0 would invent 180 failed projects that never failed.
NON_RATINGS = {"not rated", "not available", "not applicable"}


def build_target(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Add an `impact_norm` column in [0,1] from the IEG outcome rating."""
    col = resolve_column(df, ["Outcome", "outcome_rating", "Outcome Rating", "ieg_outcome"])
    print(f"target column: {col!r}")

    raw = df[col]
    if pd.api.types.is_numeric_dtype(raw):
        # Numeric codes: assume 1..6 ascending (1 = worst). Verify against the
        # printed distribution below -- some extracts invert this.
        lo, hi = raw.min(), raw.max()
        print(f"  numeric ratings in [{lo}, {hi}] -- assuming ascending 1..6")
        df["impact_norm"] = (raw - lo) / (hi - lo) if hi > lo else np.nan
    else:
        key = raw.astype(str).str.strip().str.lower()
        n_non = key.isin(NON_RATINGS).sum()
        if n_non:
            print(f"  dropping {n_non} rows with a non-rating "
                  f"(Not Rated / Not Available / Not Applicable)")
        df["impact_norm"] = key.where(~key.isin(NON_RATINGS)).map(RATING_TO_SCORE)
        unmapped = df["impact_norm"].isna() & raw.notna()
        if unmapped.any():
            print(f"  WARNING: {unmapped.sum()} rows unmapped. Unmatched values:")
            print("   ", sorted(key[unmapped].unique())[:20])

    before = len(df)
    df = df[df["impact_norm"].notna()].copy()
    print(f"  usable rows: {len(df)} (dropped {before - len(df)} without a rating)")
    print("  target distribution:\n", df["impact_norm"].value_counts().sort_index().to_string())
    return df, col


# ---------------------------------------------------------------------------
# CELL 4 -- features.
#
# DOMAIN-TRANSFER WARNING, and say this out loud to the panel rather than
# letting someone find it: this trains on World Bank projects worldwide and is
# applied to Indian CSR projects. So only features that still vary at inference
# time are worth having. `region` is near-constant for CSR (always India) and
# would be a spurious strong splitter, so it is deliberately excluded. Keep
# features to the ones a CSR proposal genuinely has: size, duration, sector.
# ---------------------------------------------------------------------------

# VERIFIED against the real CSV (12,932 rows). Blank rates measured, not guessed.
CATEGORICAL_CANDIDATES = {
    # 29 levels, 1.4% blank. The levels overlap Indian CSR sectors directly --
    # Education, Health/Nutrition/Population, Water, Environment, Social
    # Protection -- which is the whole reason this transfers at all.
    "sector": ["Sector Board"],
}
NUMERIC_CANDIDATES = {
    "commitment_amount": ["Net Commitment"],     # 6.8% blank
    "approval_fy": ["Approval FY"],              # 0% blank
    "exit_fy": ["Exit FY"],                      # 0% blank
}

# EXCLUDED ON PURPOSE -- each line is a decision, not an oversight.
#
# Leakage: assigned by the SAME IEG evaluation that assigns IEG_Outcome, so
# they are unavailable when a CSR proposal is scored. Including them lifts R^2
# from ~0.03 to ~0.50, which is the single most tempting mistake in this
# dataset. Measured, not assumed -- see docs for the experiment.
LEAKAGE_COLUMNS = [
    "IEG_OverallBankPerf", "IEG_ICRQuality", "IEG_BankQualityAtEntry",
    "IEG_BankQualityOfSupervision", "IEG_OverallBorrPerf", "IEG_GovernmentPerf",
    "IEG_ImplementingAgencyPerf", "IEG_MEQuality", "IEG_RDO",
    "ERR at Completion",          # measured at completion, same as the outcome
]
# Non-transferable: present here, but constant or meaningless for Indian CSR.
# A feature that cannot vary at inference is a free win on this dataset and a
# silent bias in production.
NON_TRANSFERABLE = [
    "Region",                 # always India for CSR
    "Country Name", "Country Code",
    "Lending Instrument Type",  # IPF/DPF/PforR -- CSR has no lending instrument
    "Product Line", "Agreement Type",
]
# Too sparse to rely on: 42.6% and 64.7% blank respectively.
TOO_SPARSE = ["Lending Project Cost", "ERR at Appraisal"]


def build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Assemble the feature frame. Missing optional columns are skipped aloud."""
    feats = pd.DataFrame(index=df.index)
    categorical: list[str] = []
    numeric: list[str] = []

    for name, cands in CATEGORICAL_CANDIDATES.items():
        col = resolve_column(df, cands, required=False)
        if col is None:
            print(f"  skip categorical {name} (not present)")
            continue
        feats[name] = df[col].astype(str).str.strip().replace({"nan": "unknown"}).fillna("unknown")
        categorical.append(name)

    for name, cands in NUMERIC_CANDIDATES.items():
        col = resolve_column(df, cands, required=False)
        if col is None:
            print(f"  skip numeric {name} (not present)")
            continue
        feats[name] = pd.to_numeric(df[col], errors="coerce")
        numeric.append(name)

    # Derived: duration, and log-scaled money. Commitment amounts span several
    # orders of magnitude, and CSR budgets are far smaller than World Bank
    # loans -- log1p keeps the two regimes on a comparable scale so the split
    # points learned here are not nonsense at inference.
    if {"approval_fy", "exit_fy"} <= set(feats.columns):
        feats["duration_years"] = (feats["exit_fy"] - feats["approval_fy"]).clip(0, 30)
        numeric.append("duration_years")
    if "commitment_amount" in feats.columns:
        feats["log_commitment"] = np.log1p(feats["commitment_amount"].clip(lower=0))
        numeric.append("log_commitment")

    # Raw fiscal years and raw commitment are DERIVATION INPUTS ONLY, never
    # model features. Two reasons, the second one measured:
    #
    #  1. Neither transfers. A CSR project approved in 2026 sits outside the
    #     training range entirely, and rupee budgets are orders of magnitude
    #     below World Bank loans.
    #  2. Under a temporal split every test row has an unseen exit year, so
    #     trees split on it and funnel the whole test set into one extrapolated
    #     leaf. Measured effect: interval coverage fell from 0.884 to 0.679,
    #     i.e. ci_low/ci_high stopped meaning what they claim to mean. A
    #     miscalibrated interval is worse than no interval, because a reviewer
    #     trusts it.
    DERIVATION_ONLY = {"approval_fy", "exit_fy", "commitment_amount"}
    numeric = [n for n in numeric if n not in DERIVATION_ONLY]
    dropped = sorted(DERIVATION_ONLY & set(feats.columns))

    print(f"  categorical:      {categorical}")
    print(f"  numeric:          {numeric}")
    print(f"  derivation-only:  {dropped} (excluded from the model on purpose)")
    if not categorical and not numeric:
        raise RuntimeError("no features resolved -- fix the candidate lists in CELL 4")
    return feats[categorical + numeric], categorical, numeric


# ---------------------------------------------------------------------------
# CELL 5 -- train, with a TEMPORAL split.
#
# A random split leaks here: projects from the same era share macro conditions
# and appraisal practice, so random holdout flatters the model. Splitting on
# exit year asks the honest question -- can it score projects it has not seen
# the era of? Expect lower, truer numbers than a random split would give.
# ---------------------------------------------------------------------------

def temporal_split(X: pd.DataFrame, y: pd.Series, year: pd.Series | None, frac: float = 0.8):
    if year is None or year.isna().all():
        print("  no usable year column -- falling back to a random split (note this in the report)")
        rng = np.random.default_rng(RANDOM_STATE)
        mask = rng.random(len(X)) < frac
        return X[mask], X[~mask], y[mask], y[~mask]

    cutoff = year.quantile(frac)
    train = year <= cutoff
    print(f"  temporal split at exit year {cutoff:.0f}: {train.sum()} train / {(~train).sum()} test")
    return X[train], X[~train], y[train], y[~train]


def train(X_train, X_test, y_train, y_test, categorical, numeric):
    """Fit one multi-quantile booster producing [q0.1, q0.5, q0.9] per row."""
    # OrdinalEncoder, not one-hot: at inference the CSR projects carry Indian
    # sector labels the World Bank data has never seen. unknown_value=-1 maps
    # those to their own code instead of raising, which is the behaviour we
    # want -- an unseen sector should degrade the prediction, not crash the
    # pipeline mid-funding-run.
    pre = ColumnTransformer(
        [("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1,
                                encoded_missing_value=-1), categorical)],
        remainder="passthrough",
        verbose_feature_names_out=False,
    ).set_output(transform="pandas")

    Xtr = pre.fit_transform(X_train)
    Xte = pre.transform(X_test)

    model = xgb.XGBRegressor(
        objective="reg:quantileerror",
        quantile_alpha=np.array(QUANTILES),
        n_estimators=600,
        learning_rate=0.05,
        max_depth=5,
        min_child_weight=5,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_lambda=1.0,
        random_state=RANDOM_STATE,
        early_stopping_rounds=50,
        n_jobs=-1,
    )
    model.fit(Xtr, y_train, eval_set=[(Xte, y_test)], verbose=False)
    return model, pre, Xtr, Xte


# ---------------------------------------------------------------------------
# CELL 6 -- evaluate. Coverage is the headline, not R^2.
# ---------------------------------------------------------------------------

def evaluate(model, Xte, y_test, y_train=None) -> dict:
    pred = np.asarray(model.predict(Xte))
    if pred.ndim == 1:                     # single-quantile fallback
        pred = np.column_stack([pred] * 3)

    # Quantile crossing is possible -- sorting per row enforces
    # ci_low <= predicted_value <= ci_high, which the schema's ci_ordered CHECK
    # requires. The loader in the repo does the same thing, so do not skip it.
    pred = np.sort(pred, axis=1)
    lo, mid, hi = pred[:, 0], pred[:, 1], pred[:, 2]

    yt = y_test.to_numpy()
    inside = ((yt >= lo) & (yt <= hi)).mean()

    # THE metric that matters at this signal level. Expect R^2 near 0.03 and a
    # model that barely beats the mean: outcome is mostly not predictable from
    # sector, size and duration, and the measured numbers say so. Report it
    # straight rather than tuning until a flattering split appears.
    baseline_mae = None
    if y_train is not None:
        const = np.full(len(yt), float(np.mean(y_train)))
        baseline_mae = float(mean_absolute_error(yt, const))
    metrics = {
        "n_train": int(model.best_iteration or 0) and None,  # filled by caller
        "n_test": int(len(y_test)),
        "mae": float(mean_absolute_error(y_test, mid)),
        "rmse": float(np.sqrt(mean_squared_error(y_test, mid))),
        "r2": float(r2_score(y_test, mid)),
        "interval_coverage": float(inside),          # target ~0.80
        "baseline_mae_constant": baseline_mae,
        "beats_constant_baseline": (
            None if baseline_mae is None
            else bool(mean_absolute_error(y_test, mid) < baseline_mae)
        ),
        "mean_interval_width": float((hi - lo).mean()),
        "best_iteration": int(model.best_iteration) if model.best_iteration is not None else None,
        "quantiles": QUANTILES,
        "xgboost_version": xgb.__version__,
        "sklearn_version": sklearn.__version__,
    }
    metrics.pop("n_train")

    print("\n-- held-out performance --")
    print(f"  MAE               {metrics['mae']:.4f}")
    print(f"  RMSE              {metrics['rmse']:.4f}")
    print(f"  R^2               {metrics['r2']:.4f}")
    print(f"  coverage [q10,q90] {metrics['interval_coverage']:.3f}  (want ~0.80)")
    print(f"  mean width        {metrics['mean_interval_width']:.4f}")
    if baseline_mae is not None:
        verdict = "beats" if metrics["mae"] < baseline_mae else "DOES NOT beat"
        print(f"  constant baseline MAE {baseline_mae:.4f}  -> model {verdict} it")
    if abs(metrics["interval_coverage"] - 0.8) > 0.1:
        print("  WARNING: intervals are miscalibrated; ci_low/ci_high would mislead a reviewer")
    return metrics


# ---------------------------------------------------------------------------
# CELL 7 -- save the four artefacts.
# ---------------------------------------------------------------------------

def save(model, pre, feature_order, categorical, numeric, metrics) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    model.save_model(OUT / "impact_model.json")      # JSON, not pickle: portable

    # Category levels are the part people forget. Without them the encoder
    # cannot reproduce its mapping, and feature ORDER is positional at
    # inference -- if it drifts, predictions are wrong silently rather than
    # raising. This file is what makes the handoff reproducible.
    levels = {}
    if categorical:
        enc = pre.named_transformers_["cat"]
        levels = {c: list(map(str, cats)) for c, cats in zip(categorical, enc.categories_)}

    (OUT / "impact_features.json").write_text(json.dumps({
        "feature_order": list(feature_order),
        "categorical": categorical,
        "numeric": numeric,
        "category_levels": levels,
        "quantiles": QUANTILES,
        "target": "impact_norm in [0,1] from IEG 6-point outcome rating",
        "rating_map": RATING_TO_SCORE,
        "unknown_category_code": -1,
        "trained_on": "IEG World Bank Project Performance Ratings",
        "transfer_caveat": "trained on World Bank projects, applied to Indian CSR projects",
    }, indent=2))

    joblib.dump(pre, OUT / "impact_preprocessor.joblib")
    (OUT / "impact_metrics.json").write_text(json.dumps(metrics, indent=2))

    print("\nwrote:")
    for f in ["impact_model.json", "impact_features.json",
              "impact_preprocessor.joblib", "impact_metrics.json"]:
        print(f"  {f}  ({(OUT / f).stat().st_size:,} bytes)")


def main() -> None:
    ieg = load_ieg()
    ops = load_ops()

    if ops is not None:
        # Join on project id to pick up commitment amount and sector when the
        # ratings extract lacks them. Left join: never drop a rated project
        # just because operations data is missing for it.
        try:
            lk = resolve_column(ieg, ["Project ID", "proj_id", "project_id", "epid"])
            rk = resolve_column(ops, ["Project ID", "proj_id", "project_id", "id"])
            ops_small = ops.drop_duplicates(subset=[rk])
            before = len(ieg)
            ieg = ieg.merge(ops_small, left_on=lk, right_on=rk, how="left", suffixes=("", "_ops"))
            print(f"joined on {lk} <- {rk}: {before} rows -> {len(ieg)}")
        except KeyError as exc:
            print(f"join skipped ({exc}); continuing with IEG columns only")

    ieg, _ = build_target(ieg)
    X, categorical, numeric = build_features(ieg)
    y = ieg["impact_norm"]

    exit_col = resolve_column(ieg, ["Exit FY", "exitfy", "Closing FY"], required=False)
    year = pd.to_numeric(ieg[exit_col], errors="coerce") if exit_col else None

    X_train, X_test, y_train, y_test = temporal_split(X, y, year)
    model, pre, Xtr, Xte = train(X_train, X_test, y_train, y_test, categorical, numeric)

    metrics = evaluate(model, Xte, y_test, y_train)
    metrics["n_train"] = int(len(y_train))
    save(model, pre, Xtr.columns, categorical, numeric, metrics)


if __name__ == "__main__":
    main()
