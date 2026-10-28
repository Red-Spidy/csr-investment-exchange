-- 11: the promised gain a progress bar is measured against, and progress ratings.
-- A rating is advice for the reviewer: storing one must never move money.
BEGIN;

DO $$
DECLARE
    v NUMERIC;
    phase_status TEXT;
    ledger_rows BIGINT;
BEGIN
    -- project 1 promises attendance from 61 to 69: a gain of 8 points
    v := fn_promised_gain(1);
    IF v IS DISTINCT FROM 8 THEN
        RAISE EXCEPTION 'FAIL 11a: promised gain for project 1 = % expected 8', v;
    END IF;
    RAISE NOTICE 'PASS 11a: promised gain is the distance from baseline to target';

    -- a target with no starting value promises nothing measurable, unless it starts from zero
    UPDATE project_extractions SET target_metric = '{"name": "x", "unit": "percentage_points", "target": 57, "baseline": null}'
     WHERE project_id = 2;
    IF fn_promised_gain(2) IS NOT NULL THEN
        RAISE EXCEPTION 'FAIL 11b: a missing baseline must give no promise, got %', fn_promised_gain(2);
    END IF;
    UPDATE project_extractions SET target_metric = '{"name": "tree_cover", "unit": "hectares", "target": 320, "baseline": null}'
     WHERE project_id = 2;
    IF fn_promised_gain(2) IS DISTINCT FROM 320 THEN
        RAISE EXCEPTION 'FAIL 11b: hectares start from zero, promise = % expected 320', fn_promised_gain(2);
    END IF;
    RAISE NOTICE 'PASS 11b: no baseline means no promise, except for measures that start from zero';

    -- ratings run from 1 to 5
    BEGIN
        UPDATE impact_reports SET rating = 6 WHERE project_id = 1;
        RAISE EXCEPTION 'FAIL 11c: a rating of 6 was stored';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
    RAISE NOTICE 'PASS 11c: a rating outside 1 to 5 is refused';

    -- rating submitted milestone evidence changes nothing about the money
    UPDATE milestones SET verification_status = 'submitted', update_text = 'Registers attached.'
     WHERE commitment_id = 1 AND phase_no = 2;
    SELECT count(*) INTO ledger_rows FROM fund_transactions;
    UPDATE milestones SET rating = 5, rating_reason = 'Ahead of pace.', rated_by = 'rules-v1', rated_at = now()
     WHERE commitment_id = 1 AND phase_no = 2;
    SELECT status::text INTO phase_status FROM fund_phases WHERE commitment_id = 1 AND phase_no = 2;
    IF phase_status <> 'locked' THEN
        RAISE EXCEPTION 'FAIL 11d: a rating moved phase 2 to %', phase_status;
    END IF;
    IF (SELECT count(*) FROM fund_transactions) <> ledger_rows THEN
        RAISE EXCEPTION 'FAIL 11d: a rating wrote to the ledger';
    END IF;
    RAISE NOTICE 'PASS 11d: a top rating releases nothing; only verification does';
END $$;

ROLLBACK;
