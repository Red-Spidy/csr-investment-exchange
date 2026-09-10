-- 01_triggers.sql -- milestone verification drives fund release.
-- Each block RAISEs on failure, so a non-zero psql exit means a real regression.
BEGIN;

DO $$
DECLARE
    c_id      BIGINT;
    n_phases  INT;
    n_miles   INT;
    sum_phase NUMERIC;
BEGIN
    -- fixture: fresh ngo/company/approved project
    INSERT INTO ngos (name, registration_no, sector, state)
    VALUES ('T Trigger NGO', 'T-TRG-1', 'education', 'Goa');

    INSERT INTO companies (name, cin, fy, avg_net_profit, mandated_csr_budget)
    VALUES ('T Trigger Co', 'T-TRG-CIN-1', 'FY24-25', 1000000, 1000000);

    INSERT INTO projects (ngo_id, title, proposal_text, sector, state,
                          requested_amount, duration_months, num_phases, status)
    VALUES (currval('ngos_id_seq'), 'T project', 'text', 'education', 'Goa',
            300000, 9, 3, 'approved');

    c_id := fn_commit_funds(currval('companies_id_seq')::bigint,
                            currval('projects_id_seq')::bigint, NULL, 300000);

    -- the AFTER INSERT trigger must have built the schedule
    SELECT count(*) INTO n_phases FROM fund_phases WHERE commitment_id = c_id;
    IF n_phases <> 3 THEN
        RAISE EXCEPTION 'FAIL: expected 3 phases, got %', n_phases;
    END IF;

    SELECT count(*) INTO n_miles FROM milestones WHERE commitment_id = c_id;
    IF n_miles <> 3 THEN
        RAISE EXCEPTION 'FAIL: expected 3 milestones, got %', n_miles;
    END IF;

    -- rounding remainder must land on the last phase: phases sum to the commitment
    SELECT sum(amount) INTO sum_phase FROM fund_phases WHERE commitment_id = c_id;
    IF sum_phase <> 300000 THEN
        RAISE EXCEPTION 'FAIL: phases sum to % not 300000', sum_phase;
    END IF;

    -- everything starts locked
    IF EXISTS (SELECT 1 FROM fund_phases WHERE commitment_id = c_id AND status <> 'locked') THEN
        RAISE EXCEPTION 'FAIL: phases should all start locked';
    END IF;

    -- verify phase 1 -> exactly one phase releases
    UPDATE milestones SET verification_status = 'verified', verified_by = 'test'
     WHERE commitment_id = c_id AND phase_no = 1;

    IF (SELECT status FROM fund_phases WHERE commitment_id = c_id AND phase_no = 1) <> 'released' THEN
        RAISE EXCEPTION 'FAIL: phase 1 did not release on verification';
    END IF;
    IF (SELECT count(*) FROM fund_phases WHERE commitment_id = c_id AND status = 'released') <> 1 THEN
        RAISE EXCEPTION 'FAIL: more than one phase released';
    END IF;

    -- ledger recorded the release
    IF (SELECT count(*) FROM fund_transactions
         WHERE commitment_id = c_id AND txn_type = 'release') <> 1 THEN
        RAISE EXCEPTION 'FAIL: release not written to ledger';
    END IF;

    -- idempotence: re-verifying must not pay twice
    UPDATE milestones SET verification_status = 'submitted'
     WHERE commitment_id = c_id AND phase_no = 1;
    UPDATE milestones SET verification_status = 'verified'
     WHERE commitment_id = c_id AND phase_no = 1;

    IF (SELECT count(*) FROM fund_transactions
         WHERE commitment_id = c_id AND txn_type = 'release') <> 1 THEN
        RAISE EXCEPTION 'FAIL: double release on re-verification';
    END IF;

    -- failed verification holds, does not release
    UPDATE milestones SET verification_status = 'failed'
     WHERE commitment_id = c_id AND phase_no = 2;

    IF (SELECT status FROM fund_phases WHERE commitment_id = c_id AND phase_no = 2) <> 'held' THEN
        RAISE EXCEPTION 'FAIL: phase 2 not held on failed verification';
    END IF;
    IF (SELECT status FROM projects WHERE id =
            (SELECT project_id FROM commitments WHERE id = c_id)) <> 'flagged' THEN
        RAISE EXCEPTION 'FAIL: project not flagged on failed verification';
    END IF;

    RAISE NOTICE 'PASS 01_triggers: schedule, release, idempotence, hold';
END $$;

ROLLBACK;
