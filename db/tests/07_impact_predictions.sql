-- 07_impact_predictions.sql -- fn_predict_impact() must match hand-computed values.
-- Runs against the seeded scenario. Every expected number below is worked out
-- by hand in the comment above it, the same way 04_window_functions.sql does,
-- because these figures go into the report.
BEGIN;

-- Base rates from ml/impact/build_baserates.py over 12,752 rated IEG projects:
--   education         mean 0.6510  q10 0.20  q90 0.80  p_sat 0.7895
--   water_sanitation  mean 0.5927  q10 0.20  q90 0.80  p_sat 0.7065
--   _global           mean 0.6156  q10 0.20  q90 0.80  p_sat 0.7324

DO $$
DECLARE
    r       impact_predictions%ROWTYPE;
    n_rows  INT;
    v_ret   NUMERIC;
BEGIN
    -- ---------------------------------------------------------------- 07a
    -- Project 1: education, claims attendance 61 -> 69, so delta = +8.
    --   predicted_value = 8 * 0.6510 = 5.2080
    --   ci_low          = 8 * 0.20   = 1.6000
    --   ci_high         = 8 * 0.80   = 6.4000
    --   impact_norm     = 0.6510 (the sector base rate itself)
    v_ret := fn_predict_impact(1);

    IF v_ret <> 0.6510 THEN
        RAISE EXCEPTION 'FAIL: fn_predict_impact(1) returned % expected 0.6510', v_ret;
    END IF;

    SELECT * INTO r FROM impact_predictions WHERE project_id = 1;

    IF r.predicted_value <> 5.2080 THEN
        RAISE EXCEPTION 'FAIL: predicted_value = % expected 5.2080', r.predicted_value;
    END IF;
    IF r.ci_low <> 1.6000 THEN
        RAISE EXCEPTION 'FAIL: ci_low = % expected 1.6000', r.ci_low;
    END IF;
    IF r.ci_high <> 6.4000 THEN
        RAISE EXCEPTION 'FAIL: ci_high = % expected 6.4000', r.ci_high;
    END IF;
    IF r.impact_norm <> 0.6510 THEN
        RAISE EXCEPTION 'FAIL: impact_norm = % expected 0.6510', r.impact_norm;
    END IF;
    -- The metric name and unit come from the NLP extraction, not from the model:
    -- the forecast is reported in the proposal's own terms.
    IF r.metric_name <> 'attendance_rate' OR r.metric_unit <> 'percentage_points' THEN
        RAISE EXCEPTION 'FAIL: metric was %/% expected attendance_rate/percentage_points',
            r.metric_name, r.metric_unit;
    END IF;
    IF r.model_version <> 'baserate-ieg-v1' THEN
        RAISE EXCEPTION 'FAIL: model_version = % expected baserate-ieg-v1', r.model_version;
    END IF;
    RAISE NOTICE 'PASS 07a: positive delta scaled by sector base rate';

    -- ---------------------------------------------------------------- 07b
    -- Project 4: water_sanitation, claims disease incidence 18 -> 12, a
    -- REDUCTION, so delta = -6 and the interval arrives inverted:
    --   predicted_value = -6 * 0.5927 = -3.5562
    --   -6 * 0.20 = -1.2  and  -6 * 0.80 = -4.8
    -- so the raw (low, high) pair is (-1.2, -4.8), which violates the
    -- ci_ordered CHECK. The function must order bounds BY VALUE, not by which
    -- quantile produced them. Expect ci_low = -4.8000, ci_high = -1.2000.
    PERFORM fn_predict_impact(4);
    SELECT * INTO r FROM impact_predictions WHERE project_id = 4;

    IF r.predicted_value <> -3.5562 THEN
        RAISE EXCEPTION 'FAIL: predicted_value = % expected -3.5562', r.predicted_value;
    END IF;
    IF r.ci_low <> -4.8000 THEN
        RAISE EXCEPTION 'FAIL: ci_low = % expected -4.8000 (bounds not reordered)', r.ci_low;
    END IF;
    IF r.ci_high <> -1.2000 THEN
        RAISE EXCEPTION 'FAIL: ci_high = % expected -1.2000 (bounds not reordered)', r.ci_high;
    END IF;
    IF NOT (r.ci_low <= r.predicted_value AND r.predicted_value <= r.ci_high) THEN
        RAISE EXCEPTION 'FAIL: ci_ordered violated for a reduction metric';
    END IF;
    RAISE NOTICE 'PASS 07b: negative delta keeps the interval correctly ordered';

    -- ---------------------------------------------------------------- 07c
    -- Project 7: education, but the proposal stated no measurable target, so
    -- project_extractions.target_metric is NULL. There is no delta to scale,
    -- and inventing a denominator is exactly what the NLP module's abstention
    -- design exists to prevent. Expect the base rate reported as itself.
    PERFORM fn_predict_impact(7);
    SELECT * INTO r FROM impact_predictions WHERE project_id = 7;

    IF r.metric_name <> 'outcome_score' OR r.metric_unit <> 'normalised_0_1' THEN
        RAISE EXCEPTION 'FAIL: absent target gave %/% expected outcome_score/normalised_0_1',
            r.metric_name, r.metric_unit;
    END IF;
    IF r.predicted_value <> 0.6510 THEN
        RAISE EXCEPTION 'FAIL: fallback predicted_value = % expected 0.6510', r.predicted_value;
    END IF;
    IF r.ci_low <> 0.2000 OR r.ci_high <> 0.8000 THEN
        RAISE EXCEPTION 'FAIL: fallback interval was [%, %] expected [0.2000, 0.8000]',
            r.ci_low, r.ci_high;
    END IF;
    RAISE NOTICE 'PASS 07c: absent target metric falls back without inventing units';

    -- ---------------------------------------------------------------- 07d
    -- Idempotence. The pipeline re-scores projects, so a second call must
    -- update in place rather than raise on the primary key or duplicate rows.
    PERFORM fn_predict_impact(1);
    PERFORM fn_predict_impact(1);
    SELECT count(*) INTO n_rows FROM impact_predictions WHERE project_id = 1;
    IF n_rows <> 1 THEN
        RAISE EXCEPTION 'FAIL: re-scoring left % rows for project 1, expected 1', n_rows;
    END IF;
    RAISE NOTICE 'PASS 07d: re-scoring is idempotent';

    -- ---------------------------------------------------------------- 07e
    -- An unmapped sector must still get a prediction from the _global row.
    -- The pipeline cannot stall on a sector with no World Bank analogue.
    UPDATE projects SET sector = 'disaster_relief' WHERE id = 2;
    PERFORM fn_predict_impact(2);
    SELECT * INTO r FROM impact_predictions WHERE project_id = 2;

    IF r.impact_norm <> 0.6156 THEN
        RAISE EXCEPTION 'FAIL: unmapped sector gave impact_norm % expected the _global 0.6156',
            r.impact_norm;
    END IF;
    RAISE NOTICE 'PASS 07e: unmapped sector falls back to the global base rate';

    -- ---------------------------------------------------------------- 07f
    -- Table-level sanity: the quantile ordering CHECK must hold for every row,
    -- and p_satisfactory must actually vary -- it is reported precisely
    -- because q10/q90 are identical across sectors on this 6-point scale.
    SELECT count(*) INTO n_rows FROM impact_sector_baserates;
    IF n_rows < 6 THEN
        RAISE EXCEPTION 'FAIL: expected >= 6 base rate rows, got %', n_rows;
    END IF;

    SELECT count(DISTINCT p_satisfactory) INTO n_rows FROM impact_sector_baserates;
    IF n_rows < 4 THEN
        RAISE EXCEPTION 'FAIL: p_satisfactory barely varies (% distinct) -- it is the '
                        'discriminating column and should differ per sector', n_rows;
    END IF;
    RAISE NOTICE 'PASS 07f: base rate table well-formed, p_satisfactory discriminates';

    RAISE NOTICE 'PASS 07_impact_predictions: scaling, sign handling, fallback, idempotence';
END $$;

ROLLBACK;
