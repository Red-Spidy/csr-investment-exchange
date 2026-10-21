-- 08_terminate.sql -- the way out of a held phase: terminate the commitment, refund
-- what was not released, and keep the books balanced. Fixtures are created inside
-- the transaction and rolled back, so it runs on a seeded or an empty database.
BEGIN;

-- Fixture: a company with room for 600,000 and a 300,000 project in 3 phases of 100,000.
CREATE FUNCTION pg_temp.fixture(tag TEXT, OUT co BIGINT, OUT pr BIGINT, OUT cm BIGINT) AS $$
DECLARE
    ngo BIGINT;
BEGIN
    INSERT INTO ngos (name, registration_no, sector, state)
    VALUES ('T Term NGO ' || tag, 'T-TERM-' || tag, 'education', 'Goa') RETURNING id INTO ngo;
    INSERT INTO companies (name, cin, fy, avg_net_profit, mandated_csr_budget)
    VALUES ('T Term Co ' || tag, 'T-TERM-CIN-' || tag, 'FY24-25', 1000000, 600000) RETURNING id INTO co;
    INSERT INTO projects (ngo_id, title, proposal_text, sector, state,
                          requested_amount, duration_months, num_phases, status)
    VALUES (ngo, 'T term project ' || tag, 'text', 'education', 'Goa', 300000, 9, 3, 'approved')
    RETURNING id INTO pr;
    cm := fn_commit_funds(co, pr, NULL, 300000);
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION pg_temp.verify(cm BIGINT, phase INT) RETURNS void AS $$
    UPDATE milestones SET verification_status = 'verified', verified_by = 'test'
     WHERE commitment_id = cm AND phase_no = phase;
$$ LANGUAGE sql;

CREATE FUNCTION pg_temp.refused(stmt TEXT) RETURNS TEXT AS $$
BEGIN
    EXECUTE stmt;
    RETURN NULL;
EXCEPTION WHEN OTHERS THEN
    RETURN SQLERRM;
END;
$$ LANGUAGE plpgsql;

-- 08a: a held phase is refunded, released phases stay paid, the ledger balances.
DO $$
DECLARE
    f        RECORD;
    refunded NUMERIC;
    said     TEXT;
BEGIN
    SELECT * INTO f FROM pg_temp.fixture('a');
    PERFORM pg_temp.verify(f.cm, 1);
    UPDATE milestones SET verification_status = 'failed' WHERE commitment_id = f.cm AND phase_no = 2;

    -- phase 3 is paid while phase 2 is still held: the commitment must stay open and flagged
    PERFORM pg_temp.verify(f.cm, 3);
    IF (SELECT status FROM commitments WHERE id = f.cm) <> 'active' THEN
        RAISE EXCEPTION 'FAIL: commitment completed with a phase still held';
    END IF;
    IF (SELECT status FROM projects WHERE id = f.pr) <> 'flagged' THEN
        RAISE EXCEPTION 'FAIL: a later release cleared the flag while a phase was held, got %',
            (SELECT status FROM projects WHERE id = f.pr);
    END IF;

    said := pg_temp.refused(format('SELECT fn_terminate_commitment(%s, '' '')', f.cm));
    IF said IS DISTINCT FROM 'a reason is required to terminate a commitment' THEN
        RAISE EXCEPTION 'FAIL: blank reason accepted or wrong error: %', said;
    END IF;
    IF (SELECT status FROM commitments WHERE id = f.cm) <> 'active' THEN
        RAISE EXCEPTION 'FAIL: a refused termination changed the commitment';
    END IF;

    refunded := fn_terminate_commitment(f.cm, 'phase 2 failed verification', 'tester');
    IF refunded <> 100000 THEN
        RAISE EXCEPTION 'FAIL: refunded % expected 100000 (only the held phase)', refunded;
    END IF;

    IF (SELECT status FROM commitments WHERE id = f.cm) <> 'cancelled' THEN
        RAISE EXCEPTION 'FAIL: commitment not cancelled';
    END IF;
    IF (SELECT status FROM projects WHERE id = f.pr) <> 'terminated' THEN
        RAISE EXCEPTION 'FAIL: project not terminated';
    END IF;
    IF (SELECT array_agg(status::text ORDER BY phase_no) FROM fund_phases WHERE commitment_id = f.cm)
           <> ARRAY['released', 'terminated', 'released'] THEN
        RAISE EXCEPTION 'FAIL: phases are %',
            (SELECT array_agg(status::text ORDER BY phase_no) FROM fund_phases WHERE commitment_id = f.cm);
    END IF;
    IF (SELECT committed_budget FROM companies WHERE id = f.co) <> 200000 THEN
        RAISE EXCEPTION 'FAIL: committed_budget is %, expected 200000 (the two released phases)',
            (SELECT committed_budget FROM companies WHERE id = f.co);
    END IF;

    -- one terminate row for the phase, one refund row for the money
    IF (SELECT count(*) FROM fund_transactions WHERE commitment_id = f.cm AND txn_type = 'terminate'
           AND amount = 100000 AND phase_id IS NOT NULL) <> 1
    OR (SELECT count(*) FROM fund_transactions WHERE commitment_id = f.cm AND txn_type = 'refund'
           AND amount = 100000 AND phase_id IS NULL) <> 1 THEN
        RAISE EXCEPTION 'FAIL: ledger is missing the terminate or refund row';
    END IF;
    -- what was locked equals what was released plus what was terminated
    IF (SELECT sum(amount) FROM fund_transactions WHERE commitment_id = f.cm AND txn_type = 'lock')
       <> (SELECT sum(amount) FROM fund_transactions
            WHERE commitment_id = f.cm AND txn_type IN ('release', 'terminate')) THEN
        RAISE EXCEPTION 'FAIL: lock does not equal release + terminate';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM audit_log WHERE entity = 'commitment' AND entity_id = f.cm
                      AND action = 'commitment_terminated'
                      AND detail->>'reason' = 'phase 2 failed verification'
                      AND detail->>'by' = 'tester'
                      AND (detail->>'refunded')::numeric = 100000
                      AND (detail->>'released')::numeric = 200000) THEN
        RAISE EXCEPTION 'FAIL: audit row missing or wrong: %',
            (SELECT detail FROM audit_log WHERE entity = 'commitment' AND entity_id = f.cm
                AND action = 'commitment_terminated');
    END IF;

    -- terminating twice
    said := pg_temp.refused(format('SELECT fn_terminate_commitment(%s, ''again'')', f.cm));
    IF said IS DISTINCT FROM format('commitment %s is cancelled, only active commitments can be terminated', f.cm) THEN
        RAISE EXCEPTION 'FAIL: second termination was not refused as expected: %', said;
    END IF;

    RAISE NOTICE 'PASS 08a: held phase refunded, released phases kept, ledger balances';
END $$;

-- 08b: nothing released yet -> everything comes back, and the freed budget can be spent again.
DO $$
DECLARE
    f        RECORD;
    other    BIGINT;
    refunded NUMERIC;
BEGIN
    SELECT * INTO f FROM pg_temp.fixture('b');
    refunded := fn_terminate_commitment(f.cm, 'NGO withdrew');
    IF refunded <> 300000 THEN
        RAISE EXCEPTION 'FAIL: refunded % expected 300000', refunded;
    END IF;
    IF (SELECT committed_budget FROM companies WHERE id = f.co) <> 0 THEN
        RAISE EXCEPTION 'FAIL: budget not fully returned';
    END IF;
    IF (SELECT count(*) FROM fund_transactions WHERE commitment_id = f.cm AND txn_type = 'terminate') <> 3 THEN
        RAISE EXCEPTION 'FAIL: expected a terminate row per phase';
    END IF;

    -- the same company can now fund a different project with the money that came back
    INSERT INTO projects (ngo_id, title, proposal_text, sector, state,
                          requested_amount, duration_months, num_phases, status)
    SELECT ngo_id, 'T term follow-on', 'text', 'education', 'Goa', 600000, 9, 2, 'approved'
      FROM projects WHERE id = f.pr RETURNING id INTO other;
    PERFORM fn_commit_funds(f.co, other, NULL, 600000);
    IF (SELECT committed_budget FROM companies WHERE id = f.co) <> 600000 THEN
        RAISE EXCEPTION 'FAIL: refunded budget could not be committed again';
    END IF;

    -- but the terminated project is not fundable again
    IF pg_temp.refused(format('SELECT fn_commit_funds(%s, %s, NULL, 100000)', f.co, f.pr)) IS NULL THEN
        RAISE EXCEPTION 'FAIL: a terminated project was funded again';
    END IF;

    RAISE NOTICE 'PASS 08b: full refund, budget reusable, terminated project stays closed';
END $$;

-- 08c: a closed commitment's milestones cannot change, so a terminated project stays terminated.
DO $$
DECLARE
    f    RECORD;
    said TEXT;
BEGIN
    SELECT * INTO f FROM pg_temp.fixture('c');
    UPDATE milestones SET verification_status = 'submitted'
     WHERE commitment_id = f.cm AND phase_no = 1;
    PERFORM fn_terminate_commitment(f.cm, 'test');

    said := pg_temp.refused(format(
        'UPDATE milestones SET verification_status = ''failed'' WHERE commitment_id = %s AND phase_no = 1', f.cm));
    IF said IS DISTINCT FROM format('commitment %s is cancelled, its milestones can no longer change', f.cm) THEN
        RAISE EXCEPTION 'FAIL: milestone of a cancelled commitment was changeable: %', said;
    END IF;
    said := pg_temp.refused(format(
        'UPDATE milestones SET verification_status = ''verified'' WHERE commitment_id = %s AND phase_no = 1', f.cm));
    IF said IS NULL THEN
        RAISE EXCEPTION 'FAIL: a milestone of a cancelled commitment was verified';
    END IF;
    IF (SELECT status FROM projects WHERE id = f.pr) <> 'terminated' THEN
        RAISE EXCEPTION 'FAIL: project left the terminated state';
    END IF;
    IF EXISTS (SELECT 1 FROM fund_transactions WHERE commitment_id = f.cm AND txn_type = 'release') THEN
        RAISE EXCEPTION 'FAIL: money was released from a cancelled commitment';
    END IF;

    RAISE NOTICE 'PASS 08c: milestones of a cancelled commitment are frozen';
END $$;

-- 08d: a completed commitment and an unknown one cannot be terminated.
DO $$
DECLARE
    f    RECORD;
    said TEXT;
BEGIN
    SELECT * INTO f FROM pg_temp.fixture('d');
    PERFORM pg_temp.verify(f.cm, 1);
    PERFORM pg_temp.verify(f.cm, 2);
    PERFORM pg_temp.verify(f.cm, 3);
    IF (SELECT status FROM commitments WHERE id = f.cm) <> 'completed' THEN
        RAISE EXCEPTION 'FAIL: fixture did not complete';
    END IF;

    said := pg_temp.refused(format('SELECT fn_terminate_commitment(%s, ''late'')', f.cm));
    IF said IS DISTINCT FROM format('commitment %s is completed, only active commitments can be terminated', f.cm) THEN
        RAISE EXCEPTION 'FAIL: completed commitment was terminable: %', said;
    END IF;
    said := pg_temp.refused('SELECT fn_terminate_commitment(-1, ''x'')');
    IF said IS DISTINCT FROM 'commitment -1 not found' THEN
        RAISE EXCEPTION 'FAIL: unknown commitment: %', said;
    END IF;

    RAISE NOTICE 'PASS 08d: only active commitments can be terminated';
END $$;

-- 08e: the leaderboard counts only what reached the NGO.
DO $$
DECLARE
    f RECORD;
    funded NUMERIC;
BEGIN
    SELECT * INTO f FROM pg_temp.fixture('e');
    PERFORM pg_temp.verify(f.cm, 1);
    SELECT total_funded INTO funded FROM ngo_leaderboard
     WHERE ngo_id = (SELECT ngo_id FROM projects WHERE id = f.pr);
    IF funded <> 300000 THEN
        RAISE EXCEPTION 'FAIL: before termination total_funded = % expected 300000', funded;
    END IF;

    PERFORM fn_terminate_commitment(f.cm, 'test');
    SELECT total_funded INTO funded FROM ngo_leaderboard
     WHERE ngo_id = (SELECT ngo_id FROM projects WHERE id = f.pr);
    IF funded <> 100000 THEN
        RAISE EXCEPTION 'FAIL: after termination total_funded = % expected 100000 (the released phase)', funded;
    END IF;

    RAISE NOTICE 'PASS 08e: leaderboard counts released money only';
END $$;

ROLLBACK;
