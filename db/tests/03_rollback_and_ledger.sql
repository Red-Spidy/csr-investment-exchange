-- 03_rollback_and_ledger.sql -- a failure mid-commitment leaves ZERO trace,
-- and the ledger cannot be rewritten after the fact.
BEGIN;

DO $$
DECLARE
    co_id  BIGINT;
    pr_id  BIGINT;
    ngo_id BIGINT;
    raised BOOLEAN;
BEGIN
    INSERT INTO ngos (name, registration_no, sector) VALUES ('T RB NGO','T-RB-1','health')
      RETURNING id INTO ngo_id;
    INSERT INTO companies (name, cin, fy, avg_net_profit, mandated_csr_budget)
    VALUES ('T RB Co','T-RB-CIN-1','FY24-25', 1000000, 900000) RETURNING id INTO co_id;

    -- project left 'pending': fn_commit_funds must refuse it
    INSERT INTO projects (ngo_id, title, proposal_text, sector, requested_amount,
                          duration_months, num_phases, status)
    VALUES (ngo_id,'T RB project','text','health', 100000, 6, 2, 'pending')
      RETURNING id INTO pr_id;

    raised := false;
    BEGIN
        PERFORM fn_commit_funds(co_id, pr_id, NULL, 100000);
    EXCEPTION WHEN OTHERS THEN
        raised := true;
    END;
    IF NOT raised THEN
        RAISE EXCEPTION 'FAIL: unapproved project was funded';
    END IF;

    -- nothing at all should have been written
    IF (SELECT count(*) FROM commitments        WHERE project_id = pr_id) <> 0
    OR (SELECT count(*) FROM fund_phases        WHERE commitment_id IN
            (SELECT id FROM commitments WHERE project_id = pr_id)) <> 0
    OR (SELECT count(*) FROM milestones         WHERE project_id = pr_id) <> 0
    OR (SELECT committed_budget FROM companies  WHERE id = co_id) <> 0 THEN
        RAISE EXCEPTION 'FAIL: partial state survived a rejected commitment';
    END IF;

    RAISE NOTICE 'PASS 03a: rejected commitment left no partial state';
END $$;

-- ledger immutability
DO $$
DECLARE
    raised BOOLEAN;
    txn_id BIGINT;
BEGIN
    SELECT id INTO txn_id FROM fund_transactions ORDER BY id LIMIT 1;
    IF txn_id IS NULL THEN
        RAISE NOTICE 'SKIP 03b: no ledger rows (run after seed)';
        RETURN;
    END IF;

    raised := false;
    BEGIN
        UPDATE fund_transactions SET amount = 1 WHERE id = txn_id;
    EXCEPTION WHEN OTHERS THEN raised := true;
    END;
    IF NOT raised THEN RAISE EXCEPTION 'FAIL: ledger row was updatable'; END IF;

    raised := false;
    BEGIN
        DELETE FROM fund_transactions WHERE id = txn_id;
    EXCEPTION WHEN OTHERS THEN raised := true;
    END;
    IF NOT raised THEN RAISE EXCEPTION 'FAIL: ledger row was deletable'; END IF;

    RAISE NOTICE 'PASS 03b: ledger is append-only';
END $$;

-- The ledger also survives deletion of its PARENT. Financial history cannot be
-- erased as a side effect of removing a company or commitment.
DO $$
DECLARE
    co_id BIGINT; raised BOOLEAN;
BEGIN
    SELECT c.company_id INTO co_id
      FROM commitments c
      JOIN fund_transactions ft ON ft.commitment_id = c.id
     LIMIT 1;

    IF co_id IS NULL THEN
        RAISE NOTICE 'SKIP 03c: no committed company (run after seed)';
        RETURN;
    END IF;

    raised := false;
    BEGIN
        DELETE FROM companies WHERE id = co_id;
    EXCEPTION WHEN OTHERS THEN raised := true;
    END;

    IF NOT raised THEN
        RAISE EXCEPTION 'FAIL: deleting a company silently erased its ledger history';
    END IF;

    RAISE NOTICE 'PASS 03c: ledger survives cascade delete of its parent';
END $$;

ROLLBACK;
