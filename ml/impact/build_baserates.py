"""Compute sector impact base rates from IEG ratings -> emit a SQL migration.

WHY THIS IS NOT A TRAINED MODEL
    Measured on the IEG data (docs/impact-model-findings.md): sector, budget and
    duration explain ~3% of outcome variance, and no gradient-boosted
    configuration beat predicting the mean. So the honest model is the thing the
    data actually supports -- a per-sector base rate with empirical quantiles.

WHAT IT PREDICTS
    The FRACTION OF PLAN DELIVERED, not an absolute metric value. IEG outcome
    ratings measure how well a project achieved what it set out to achieve, so
    a base rate of 0.65 reads as "projects in this sector historically deliver
    about 65% of what they promised". Combined with the claimed delta that
    ml/nlp already extracts (target_metric.baseline -> target), that produces a
    forecast in the proposal's OWN units with an honest interval.

WHY QUANTILES ARE EMPIRICAL
    q10/q90 are read straight off the historical distribution rather than fitted,
    so interval coverage is correct by construction instead of by luck. This is
    the specific failure that sank the boosted version: its intervals drifted to
    0.68 and 0.93 coverage against a 0.80 target depending on featurisation.

USAGE
    IEG_CSV=path/to/ieg.csv .venv/bin/python ml/impact/build_baserates.py
    -> writes db/migrations/006_impact_baserates.sql
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

IEG_CSV = Path(os.environ.get("IEG_CSV", "ml/data/ieg-world-bank-project-performance-ratings.csv"))
OUT_SQL = Path(os.environ.get("OUT_SQL", "db/migrations/006_impact_baserates.sql"))

# IEG's 6-point ordinal outcome scale -> [0,1].
RATING_TO_SCORE = {
    "highly unsatisfactory": 0.0,
    "unsatisfactory": 0.2,
    "moderately unsatisfactory": 0.4,
    "moderately satisfactory": 0.6,
    "satisfactory": 0.8,
    "highly satisfactory": 1.0,
}
# Not ratings. Dropped, never mapped to 0.0 -- scoring these as failures would
# invent ~180 failed projects that never failed.
NON_RATINGS = {"not rated", "not available", "not applicable"}

# World Bank 'Sector Board' -> this project's CSR sector vocabulary.
# Pooling happens on the CSR side so quantiles come from the real combined
# population rather than from averaging per-sector summaries.
SECTOR_MAP = {
    "Education":                                 "education",
    "Health, Nutrition and Population":          "healthcare",
    "Water":                                     "water_sanitation",
    "Environment":                               "environment",
    # 'livelihood' in CSR terms is income generation, which is what these three
    # World Bank boards fund.
    "Agriculture and Rural Development":         "livelihood",
    "Social Protection":                         "livelihood",
    "Financial and Private Sector Development":  "livelihood",
}
GLOBAL_KEY = "_global"      # fallback for any sector with no mapped history
MIN_N = 100                 # below this, a sector's quantiles are noise

# "Moderately Satisfactory" or better. P(outcome >= this) is the number that
# actually discriminates between sectors -- see the note on blunt deciles in
# summarise().
SATISFACTORY_THRESHOLD = 0.6


def load() -> pd.DataFrame:
    if not IEG_CSV.exists():
        sys.exit(f"not found: {IEG_CSV}\nset IEG_CSV=<path to the Kaggle csv>")
    df = pd.read_csv(IEG_CSV, low_memory=False)
    # Five real columns ship with trailing spaces; normalise once.
    df.columns = [c.strip() for c in df.columns]
    return df


def score(df: pd.DataFrame) -> pd.DataFrame:
    key = df["IEG_Outcome"].astype(str).str.strip().str.lower()
    dropped = int(key.isin(NON_RATINGS).sum())
    df = df.assign(outcome=key.where(~key.isin(NON_RATINGS)).map(RATING_TO_SCORE))
    unmapped = df["outcome"].isna().sum() - dropped
    if unmapped > 0:
        print(f"  WARNING: {unmapped} rows had an unrecognised rating")
    df = df[df["outcome"].notna()].copy()
    print(f"  dropped {dropped} non-ratings; {len(df)} rated projects remain")
    return df


def summarise(df: pd.DataFrame) -> pd.DataFrame:
    df = df.assign(csr_sector=df["Sector Board"].map(SECTOR_MAP))

    rows = []
    # Global fallback uses EVERY rated project, not just the mapped ones: an
    # unmapped CSR sector should fall back to the broadest base rate available.
    g = df["outcome"]
    rows.append({
        "sector": GLOBAL_KEY, "n_projects": len(g),
        "mean_outcome": g.mean(), "q10": g.quantile(0.10), "q90": g.quantile(0.90),
        "p_satisfactory": (g >= SATISFACTORY_THRESHOLD).mean(),
        "source": "IEG all rated projects",
    })

    for sector, grp in df[df["csr_sector"].notna()].groupby("csr_sector"):
        o = grp["outcome"]
        if len(o) < MIN_N:
            print(f"  skipping {sector}: n={len(o)} < {MIN_N}, quantiles would be noise")
            continue
        boards = sorted(grp["Sector Board"].unique())
        rows.append({
            "sector": sector, "n_projects": len(o),
            "mean_outcome": o.mean(), "q10": o.quantile(0.10), "q90": o.quantile(0.90),
            "p_satisfactory": (o >= SATISFACTORY_THRESHOLD).mean(),
            "source": "IEG: " + "; ".join(boards),
        })

    out = pd.DataFrame(rows).sort_values("sector").reset_index(drop=True)
    for c in ("mean_outcome", "q10", "q90", "p_satisfactory"):
        out[c] = out[c].round(4)

    # Say this out loud rather than letting a reviewer think the table is
    # broken. The IEG scale has six discrete levels and 48% of all projects sit
    # at 0.8 ("Satisfactory"), so the 10th and 90th percentiles land on the same
    # two levels in every sector. The identical columns are a property of the
    # rating scale, not a copy-paste error -- and they restate the headline
    # finding: sector moves the MEAN by a few points while project-level spread
    # dominates. p_satisfactory is reported because it does discriminate.
    if out["q10"].nunique() == 1 and out["q90"].nunique() == 1:
        print(f"\n  NOTE: q10/q90 identical across sectors "
              f"({out.q10.iloc[0]:.2f}/{out.q90.iloc[0]:.2f}) -- expected, see summarise()")
    return out


def emit(stats: pd.DataFrame) -> None:
    def lit(s: str) -> str:
        return "'" + str(s).replace("'", "''") + "'"

    values = ",\n".join(
        f"  ({lit(r.sector)}, {r.n_projects}, {r.mean_outcome:.4f}, "
        f"{r.q10:.4f}, {r.q90:.4f}, {r.p_satisfactory:.4f}, {lit(r.source)})"
        for r in stats.itertuples()
    )

    OUT_SQL.write_text(f"""\
-- 006_impact_baserates.sql -- GENERATED by ml/impact/build_baserates.py
-- Do not hand-edit: re-run the script to regenerate.
--
-- Sector impact base rates from the IEG World Bank project performance
-- ratings ({int(stats.loc[stats.sector == GLOBAL_KEY, 'n_projects'].iloc[0]):,} rated projects).
--
-- This replaces the XGBoost impact model deliberately. Measured on the same
-- data, sector/budget/duration explain ~3% of outcome variance and no boosted
-- configuration beat predicting the mean -- see docs/impact-model-findings.md.
-- What survives measurement is a per-sector base rate with EMPIRICAL
-- quantiles, whose interval coverage is correct by construction.
--
-- Semantics: mean_outcome is the historical FRACTION OF PLAN DELIVERED. 0.65
-- reads as "projects in this sector delivered about 65% of what they promised".

CREATE TABLE impact_sector_baserates (
    sector       TEXT PRIMARY KEY,
    n_projects   INT NOT NULL CHECK (n_projects > 0),
    mean_outcome NUMERIC(5,4) NOT NULL CHECK (mean_outcome BETWEEN 0 AND 1),
    q10          NUMERIC(5,4) NOT NULL CHECK (q10 BETWEEN 0 AND 1),
    q90          NUMERIC(5,4) NOT NULL CHECK (q90 BETWEEN 0 AND 1),
    -- P(outcome >= Moderately Satisfactory). Reported because q10/q90 are
    -- blunt: the IEG scale has six levels and 48% of projects sit on one of
    -- them, so the deciles are identical across sectors while THIS varies.
    p_satisfactory NUMERIC(5,4) NOT NULL CHECK (p_satisfactory BETWEEN 0 AND 1),
    source       TEXT NOT NULL,
    computed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT baserate_quantiles_ordered CHECK (q10 <= mean_outcome AND mean_outcome <= q90)
);

INSERT INTO impact_sector_baserates
  (sector, n_projects, mean_outcome, q10, q90, p_satisfactory, source) VALUES
{values};

-- ---------------------------------------------------------------- prediction

-- Turn a sector base rate plus the NLP-extracted claim into a forecast in the
-- proposal's own units.
--
-- Two branches, and the second one is the point of the NLP module's
-- abstention design:
--   * target_metric present  -> scale the claimed delta by the base rate, so
--     the forecast is in percentage_points / hectares / whatever was claimed.
--   * target_metric absent   -> the proposal never stated a measurable target,
--     so there is nothing to scale. Fall back to reporting the normalised
--     outcome score itself rather than inventing a denominator.
CREATE FUNCTION fn_predict_impact(p_project_id BIGINT) RETURNS NUMERIC AS $$
DECLARE
    pr        projects%ROWTYPE;
    br        impact_sector_baserates%ROWTYPE;
    tm        JSONB;
    v_base    NUMERIC;
    v_target  NUMERIC;
    v_delta   NUMERIC;
    v_name    TEXT;
    v_unit    TEXT;
    v_pred    NUMERIC;
    v_lo      NUMERIC;
    v_hi      NUMERIC;
BEGIN
    SELECT * INTO pr FROM projects WHERE id = p_project_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'project % not found', p_project_id;
    END IF;

    -- Sector-specific base rate, else the global fallback. An unmapped sector
    -- must still get a prediction: the pipeline cannot stall on a project
    -- whose sector has no World Bank analogue.
    SELECT * INTO br FROM impact_sector_baserates WHERE sector = pr.sector;
    IF NOT FOUND THEN
        SELECT * INTO br FROM impact_sector_baserates WHERE sector = '_global';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'no base rate for sector % and no _global fallback', pr.sector;
        END IF;
    END IF;

    SELECT target_metric INTO tm FROM project_extractions WHERE project_id = p_project_id;

    v_base   := NULLIF(tm->>'baseline', '')::NUMERIC;
    v_target := NULLIF(tm->>'target', '')::NUMERIC;
    v_name   := NULLIF(tm->>'name', '');
    v_unit   := NULLIF(tm->>'unit', '');

    IF v_base IS NOT NULL AND v_target IS NOT NULL AND v_target <> v_base THEN
        v_delta := v_target - v_base;                 -- the claimed improvement
        v_pred  := round(v_delta * br.mean_outcome, 4);
        v_lo    := round(v_delta * br.q10, 4);
        v_hi    := round(v_delta * br.q90, 4);
        -- A claimed REDUCTION makes delta negative, which flips the interval.
        -- ci_ordered would reject that, so order the bounds by value, not by
        -- which quantile produced them.
        IF v_lo > v_hi THEN
            v_delta := v_lo; v_lo := v_hi; v_hi := v_delta;
        END IF;
        v_name := COALESCE(v_name, 'unnamed_metric');
        v_unit := COALESCE(v_unit, 'unknown');
    ELSE
        -- Nothing measurable was claimed. Report the base rate itself.
        v_pred := br.mean_outcome;
        v_lo   := br.q10;
        v_hi   := br.q90;
        v_name := 'outcome_score';
        v_unit := 'normalised_0_1';
    END IF;

    INSERT INTO impact_predictions
        (project_id, metric_name, metric_unit, predicted_value,
         ci_low, ci_high, impact_norm, model_version)
    VALUES (p_project_id, v_name, v_unit, v_pred, v_lo, v_hi,
            br.mean_outcome, 'baserate-ieg-v1')
    ON CONFLICT (project_id) DO UPDATE SET
        metric_name     = EXCLUDED.metric_name,
        metric_unit     = EXCLUDED.metric_unit,
        predicted_value = EXCLUDED.predicted_value,
        ci_low          = EXCLUDED.ci_low,
        ci_high         = EXCLUDED.ci_high,
        impact_norm     = EXCLUDED.impact_norm,
        model_version   = EXCLUDED.model_version,
        predicted_at    = now();

    RETURN br.mean_outcome;
END;
$$ LANGUAGE plpgsql;
""")


def main() -> None:
    print(f"reading {IEG_CSV}")
    stats = summarise(score(load()))
    print("\n" + stats.to_string(index=False))
    emit(stats)
    print(f"\nwrote {OUT_SQL}")


if __name__ == "__main__":
    main()
