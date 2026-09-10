-- 04_window_functions.sql -- window view output must match hand-computed values.
-- Runs against the seeded scenario (project 1, six monthly reports).
BEGIN;

DO $$
DECLARE
    r RECORD;
BEGIN
    -- seeded monthly values: 1.20, 2.05, 3.10, 4.40, 5.60, 6.90
    -- cumulative at Aug = 23.25 ; MoM delta Aug = 6.90-5.60 = 1.30
    -- rolling 3mo at Aug = (4.40+5.60+6.90)/3 = 5.6333
    SELECT * INTO r
      FROM company_esg_timeline
     WHERE company_id = 1 AND month = DATE '2026-08-01';

    IF r IS NULL THEN
        RAISE EXCEPTION 'FAIL: no timeline row for Aug 2026 (did seed run?)';
    END IF;

    IF r.cumulative_impact <> 23.25 THEN
        RAISE EXCEPTION 'FAIL: cumulative_impact = % expected 23.25', r.cumulative_impact;
    END IF;

    IF r.mom_delta <> 1.30 THEN
        RAISE EXCEPTION 'FAIL: mom_delta = % expected 1.30', r.mom_delta;
    END IF;

    IF round(r.rolling_3mo_esg, 4) <> 5.6333 THEN
        RAISE EXCEPTION 'FAIL: rolling_3mo_esg = % expected 5.6333', r.rolling_3mo_esg;
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
