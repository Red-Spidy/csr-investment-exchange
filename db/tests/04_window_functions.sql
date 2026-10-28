-- 04_window_functions.sql -- window view output must match hand-computed values.
-- Runs against the seeded scenario (project 1, six monthly reports).
BEGIN;

DO $$
DECLARE
    r RECORD;
BEGIN
    -- seeded monthly gains: 1.20, 0.85, 1.05, 1.30, 1.20, 1.30 (each month's gain, not a total)
    -- cumulative at Aug = 6.90 ; MoM delta Aug = 1.30-1.20 = 0.10
    -- rolling 3mo at Aug = (1.30+1.20+1.30)/3 = 1.2667
    SELECT * INTO r
      FROM company_esg_timeline
     WHERE company_id = 1 AND month = DATE '2026-08-01';

    IF r IS NULL THEN
        RAISE EXCEPTION 'FAIL: no timeline row for Aug 2026 (did seed run?)';
    END IF;

    IF r.cumulative_impact <> 6.90 THEN
        RAISE EXCEPTION 'FAIL: cumulative_impact = % expected 6.90', r.cumulative_impact;
    END IF;

    IF r.mom_delta <> 0.10 THEN
        RAISE EXCEPTION 'FAIL: mom_delta = % expected 0.10', r.mom_delta;
    END IF;

    IF round(r.rolling_3mo_esg, 4) <> 1.2667 THEN
        RAISE EXCEPTION 'FAIL: rolling_3mo_esg = % expected 1.2667', r.rolling_3mo_esg;
    END IF;

    -- first month has no predecessor: delta must be NULL, rolling = the value itself
    SELECT * INTO r
      FROM company_esg_timeline
     WHERE company_id = 1 AND month = DATE '2026-03-01';

    IF r.mom_delta IS NOT NULL THEN
        RAISE EXCEPTION 'FAIL: first month mom_delta should be NULL, got %', r.mom_delta;
    END IF;
    IF round(r.rolling_3mo_esg, 4) <> 1.2000 THEN
        RAISE EXCEPTION 'FAIL: first month rolling = % expected 1.2000', r.rolling_3mo_esg;
    END IF;
    IF r.cumulative_impact <> 1.20 THEN
        RAISE EXCEPTION 'FAIL: first month cumulative = % expected 1.20', r.cumulative_impact;
    END IF;

    RAISE NOTICE 'PASS 04_window_functions: running total, MoM delta, 3-month rolling';
END $$;

ROLLBACK;
