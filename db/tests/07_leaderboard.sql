-- 07_leaderboard.sql -- ngo_leaderboard must count each commitment once, however
-- many monthly impact reports the project has. Runs against the seeded scenario.
BEGIN;

DO $$
DECLARE
    r RECORD;
BEGIN
    -- NGO 1 owns project 1 (Meridian funded 2,400,000; six monthly gains summing 6.90)
    -- and the unfunded project 7.
    SELECT * INTO r FROM ngo_leaderboard WHERE ngo_id = 1;

    IF r IS NULL THEN
        RAISE EXCEPTION 'FAIL: no leaderboard row for NGO 1 (did seed run?)';
    END IF;
    IF r.project_count <> 2 THEN
        RAISE EXCEPTION 'FAIL: project_count = % expected 2', r.project_count;
    END IF;
    IF r.total_funded <> 2400000.00 THEN
        RAISE EXCEPTION 'FAIL: total_funded = % expected 2400000.00 (commitment counted once per report?)',
            r.total_funded;
    END IF;
    IF r.total_impact <> 6.90 THEN
        RAISE EXCEPTION 'FAIL: total_impact = % expected 6.90', r.total_impact;
    END IF;
    -- 6.90 / 2,400,000 * 1,000,000
    IF r.impact_per_million <> 2.8750 THEN
        RAISE EXCEPTION 'FAIL: impact_per_million = % expected 2.8750', r.impact_per_million;
    END IF;

    -- an NGO with nothing funded has no impact-per-rupee figure
    SELECT * INTO r FROM ngo_leaderboard WHERE ngo_id = 2;
    IF r.total_funded <> 0 OR r.impact_per_million IS NOT NULL THEN
        RAISE EXCEPTION 'FAIL: unfunded NGO 2 shows funded=% per_million=%',
            r.total_funded, r.impact_per_million;
    END IF;

    -- fund NGO 2's project and report three months: funding must stay 1,800,000
    PERFORM fn_commit_funds(2, 2, NULL, 1800000);
    INSERT INTO impact_reports (project_id, period_month, metric_value) VALUES
        (2, DATE '2026-06-01', 0.50),
        (2, DATE '2026-07-01', 1.00),
        (2, DATE '2026-08-01', 1.50);

    SELECT * INTO r FROM ngo_leaderboard WHERE ngo_id = 2;
    IF r.total_funded <> 1800000.00 THEN
        RAISE EXCEPTION 'FAIL: NGO 2 total_funded = % expected 1800000.00', r.total_funded;
    END IF;
    IF r.total_impact <> 3.00 THEN
        RAISE EXCEPTION 'FAIL: NGO 2 total_impact = % expected 3.00', r.total_impact;
    END IF;
    -- 3 / 1,800,000 * 1,000,000 = 1.6667
    IF r.impact_per_million <> 1.6667 THEN
        RAISE EXCEPTION 'FAIL: NGO 2 impact_per_million = % expected 1.6667', r.impact_per_million;
    END IF;

    -- NGO 1 (2.8750) now outranks NGO 2 (1.6667) in the education sector
    SELECT * INTO r FROM ngo_leaderboard WHERE ngo_id = 1;
    IF r.sector_rank <> 1 THEN
        RAISE EXCEPTION 'FAIL: NGO 1 sector_rank = % expected 1', r.sector_rank;
    END IF;
    SELECT * INTO r FROM ngo_leaderboard WHERE ngo_id = 2;
    IF r.sector_rank <> 2 THEN
        RAISE EXCEPTION 'FAIL: NGO 2 sector_rank = % expected 2', r.sector_rank;
    END IF;

    RAISE NOTICE 'PASS 07_leaderboard: funding counted once per commitment, ranks follow impact per rupee';
END $$;

ROLLBACK;
