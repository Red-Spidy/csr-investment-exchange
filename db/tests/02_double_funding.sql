-- 02_double_funding.sql -- a project can never carry two active commitments,
-- and a company can never commit past its mandated budget.
BEGIN;

DO $$
DECLARE
    co_id   BIGINT;
    pr_id   BIGINT;
    ngo_id  BIGINT;
    raised  BOOLEAN;
BEGIN
    INSERT INTO ngos (name, registration_no, sector) VALUES ('T DF NGO','T-DF-1','education')
      RETURNING id INTO ngo_id;
    INSERT INTO companies (name, cin, fy, avg_net_profit, mandated_csr_budget)
    VALUES ('T DF Co','T-DF-CIN-1','FY24-25', 1000000, 500000) RETURNING id INTO co_id;
    INSERT INTO projects (ngo_id, title, proposal_text, sector, requested_amount,
                          duration_months, num_phases, status)
    VALUES (ngo_id,'T DF project','text','education', 200000, 6, 2, 'approved')
      RETURNING id INTO pr_id;

    PERFORM fn_commit_funds(co_id, pr_id, NULL, 200000);

    -- second commitment on the same project must be rejected
    raised := false;
    BEGIN
        PERFORM fn_commit_funds(co_id, pr_id, NULL, 200000);
    EXCEPTION WHEN OTHERS THEN
        raised := true;
    END;
    IF NOT raised THEN
        RAISE EXCEPTION 'FAIL: double funding was allowed';
    END IF;

    -- budget accounting stayed correct after the rejected attempt
    IF (SELECT committed_budget FROM companies WHERE id = co_id) <> 200000 THEN
        RAISE EXCEPTION 'FAIL: committed_budget corrupted by rejected commitment, got %',
            (SELECT committed_budget FROM companies WHERE id = co_id);
    END IF;

    -- over-budget commitment on a DIFFERENT project must also be rejected
    INSERT INTO projects (ngo_id, title, proposal_text, sector, requested_amount,
                          duration_months, num_phases, status)
    VALUES (ngo_id,'T DF project 2','text','education', 400000, 6, 2, 'approved')
      RETURNING id INTO pr_id;

    raised := false;
    BEGIN
        PERFORM fn_commit_funds(co_id, pr_id, NULL, 400000);  -- 200k + 400k > 500k
    EXCEPTION WHEN OTHERS THEN
        raised := true;
    END;
    IF NOT raised THEN
        RAISE EXCEPTION 'FAIL: over-budget commitment was allowed';
    END IF;

    -- and no partial state was left behind by the failed attempt
    IF (SELECT count(*) FROM commitments WHERE project_id = pr_id) <> 0 THEN
        RAISE EXCEPTION 'FAIL: rejected commitment left a row behind';
    END IF;
    IF (SELECT committed_budget FROM companies WHERE id = co_id) <> 200000 THEN
        RAISE EXCEPTION 'FAIL: budget moved despite rejected commitment';
    END IF;

    RAISE NOTICE 'PASS 02_double_funding: duplicate rejected, over-budget rejected, no partial state';
END $$;

-- ---------------------------------------------------------------------------
-- Defence in depth. fn_commit_funds' status check rejects the ordinary second
-- commitment BEFORE the guard trigger or the unique index are ever reached, so
-- those two layers must be exercised directly -- they exist to catch a code path
-- that writes to commitments without going through fn_commit_funds.
-- ---------------------------------------------------------------------------

-- Layer 2: the BEFORE INSERT guard trigger.
DO $$
DECLARE
    co_id BIGINT; pr_id BIGINT; ngo_id BIGINT; raised BOOLEAN; msg TEXT;
BEGIN
    INSERT INTO ngos (name, registration_no, sector) VALUES ('T G NGO','T-G-1','education')
      RETURNING id INTO ngo_id;
    INSERT INTO companies (name, cin, fy, avg_net_profit, mandated_csr_budget)
    VALUES ('T G Co','T-G-CIN-1','FY24-25', 1000000, 900000) RETURNING id INTO co_id;
    INSERT INTO projects (ngo_id, title, proposal_text, sector, requested_amount,
                          duration_months, num_phases, status)
    VALUES (ngo_id,'T G project','text','education', 100000, 6, 2, 'approved')
      RETURNING id INTO pr_id;

    -- direct insert, bypassing fn_commit_funds entirely
    INSERT INTO commitments (company_id, project_id, amount, num_phases)
    VALUES (co_id, pr_id, 100000, 2);

    raised := false;
    BEGIN
        INSERT INTO commitments (company_id, project_id, amount, num_phases)
        VALUES (co_id, pr_id, 100000, 2);
    EXCEPTION WHEN OTHERS THEN
        raised := true; msg := SQLERRM;
    END;

    IF NOT raised THEN
        RAISE EXCEPTION 'FAIL: guard trigger did not block a direct duplicate insert';
    END IF;
    IF msg NOT LIKE '%already has active commitment%' THEN
        RAISE EXCEPTION 'FAIL: blocked, but not by the guard trigger (got: %)', msg;
    END IF;

    RAISE NOTICE 'PASS 02b: guard trigger blocks direct duplicate insert';
END $$;

-- Layer 3: the partial unique index, with the guard trigger disabled so it is
-- provably the thing doing the work.
DO $$
DECLARE
    co_id BIGINT; pr_id BIGINT; ngo_id BIGINT; raised BOOLEAN; msg TEXT;
BEGIN
    INSERT INTO ngos (name, registration_no, sector) VALUES ('T U NGO','T-U-1','education')
      RETURNING id INTO ngo_id;
    INSERT INTO companies (name, cin, fy, avg_net_profit, mandated_csr_budget)
    VALUES ('T U Co','T-U-CIN-1','FY24-25', 1000000, 900000) RETURNING id INTO co_id;
    INSERT INTO projects (ngo_id, title, proposal_text, sector, requested_amount,
                          duration_months, num_phases, status)
    VALUES (ngo_id,'T U project','text','education', 100000, 6, 2, 'approved')
      RETURNING id INTO pr_id;

    ALTER TABLE commitments DISABLE TRIGGER trg_guard_double_funding;

    INSERT INTO commitments (company_id, project_id, amount, num_phases)
    VALUES (co_id, pr_id, 100000, 2);

    raised := false;
    BEGIN
        INSERT INTO commitments (company_id, project_id, amount, num_phases)
        VALUES (co_id, pr_id, 100000, 2);
    EXCEPTION WHEN unique_violation THEN
        raised := true; msg := SQLERRM;
    END;

    ALTER TABLE commitments ENABLE TRIGGER trg_guard_double_funding;

    IF NOT raised THEN
        RAISE EXCEPTION 'FAIL: partial unique index did not block the duplicate';
    END IF;

    RAISE NOTICE 'PASS 02c: partial unique index is a working backstop';
END $$;

ROLLBACK;
