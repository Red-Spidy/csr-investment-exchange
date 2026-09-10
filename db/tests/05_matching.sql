-- 05_matching.sql -- pgvector matching returns the semantically right project
-- and respects every structured filter. Runs against the seeded scenario.
--
-- NOTE: seed's golden path funds project 1, moving it to 'active'. It must
-- therefore NOT appear in the pool -- an already-funded project can never be
-- re-matched. That exclusion is asserted explicitly below.
BEGIN;

DO $$
DECLARE
    top    RECORD;
    n_rows INT;
BEGIN
    -- rulebook 1 = "rural school attendance, northern India" -> education topic
    SELECT * INTO top FROM fn_match_projects(1, 5) LIMIT 1;

    IF top IS NULL THEN
        RAISE EXCEPTION 'FAIL: no matches for rulebook 1 (did seed run?)';
    END IF;

    -- project 1 is the closest education project semantically, but it is already
    -- funded, so project 2 must be surfaced instead.
    IF top.project_id <> 2 THEN
        RAISE EXCEPTION 'FAIL: expected project 2 top match, got % (%)',
            top.project_id, top.title;
    END IF;
    -- Assert RANKING, not an absolute similarity. Absolute cosine values depend
    -- on which embedding model produced the vectors (the seed ships synthetic
    -- topic vectors; the real pipeline writes MiniLM ones), but the ordering
    -- must hold either way.
    IF EXISTS (
        SELECT 1 FROM fn_match_projects(1, 10)
         WHERE project_id <> top.project_id AND similarity >= top.similarity
    ) THEN
        RAISE EXCEPTION 'FAIL: project % did not rank strictly first', top.project_id;
    END IF;

    -- an already-committed project must never re-enter the match pool
    IF EXISTS (SELECT 1 FROM fn_match_projects(1, 10) WHERE project_id = 1) THEN
        RAISE EXCEPTION 'FAIL: funded project 1 reappeared in the match pool';
    END IF;

    -- flagged projects must never surface: 7 and 8 are grade D
    IF EXISTS (SELECT 1 FROM fn_match_projects(1, 10) WHERE project_id IN (7, 8)) THEN
        RAISE EXCEPTION 'FAIL: flagged project appeared in match pool';
    END IF;

    -- healthcare rulebook must rank the healthcare project first
    SELECT * INTO top FROM fn_match_projects(2, 5) LIMIT 1;
    IF top.project_id <> 3 THEN
        RAISE EXCEPTION 'FAIL: healthcare rulebook ranked project % first, not 3', top.project_id;
    END IF;
    -- ...and an off-topic project that only shares an SDG must rank strictly below
    IF EXISTS (SELECT 1 FROM fn_match_projects(2, 5)
                WHERE project_id <> 3 AND similarity >= top.similarity) THEN
        RAISE EXCEPTION 'FAIL: off-topic project matched healthcare rulebook as well as project 3';
    END IF;

    -- budget ceiling: rulebook 3 caps at 3,000,000 so the 4.2M project is excluded
    SELECT count(*) INTO n_rows
      FROM fn_match_projects(3, 10) WHERE requested_amount > 3000000;
    IF n_rows <> 0 THEN
        RAISE EXCEPTION 'FAIL: budget ceiling not enforced, % rows over cap', n_rows;
    END IF;

    -- state filter: rulebook 1 prefers Rajasthan/Bihar only
    IF EXISTS (
        SELECT 1 FROM fn_match_projects(1, 10) m
          JOIN projects p ON p.id = m.project_id
         WHERE p.state NOT IN ('Rajasthan','Bihar')
    ) THEN
        RAISE EXCEPTION 'FAIL: state filter not enforced';
    END IF;

    RAISE NOTICE 'PASS 05_matching: semantic rank, funded/flagged exclusion, budget + state filters';
END $$;

ROLLBACK;
