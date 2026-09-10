-- 004_functions_triggers.sql
-- The automation core. Money only moves through the functions in this file.

-- ---------------------------------------------------------------- housekeeping

CREATE FUNCTION fn_touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_projects_touch
    BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION fn_touch_updated_at();

-- The ledger is append-only. Enforce it rather than merely documenting it.
-- Note this also blocks CASCADE deletes: removing a company cannot silently
-- erase its funding history. Deleting a commitment's ledger rows therefore
-- requires explicitly disabling this trigger, which is the point -- financial
-- history cannot be destroyed as a side effect of deleting something else.
CREATE FUNCTION fn_ledger_is_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'fund_transactions is append-only (attempted % on id %)',
        TG_OP, COALESCE(OLD.id, NEW.id);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ledger_immutable
    BEFORE UPDATE OR DELETE ON fund_transactions
    FOR EACH ROW EXECUTE FUNCTION fn_ledger_is_append_only();

-- ---------------------------------------------------------------- double-funding guard

-- First line of defence. The partial unique index in 002 is the second, and the
-- companies_within_budget CHECK is the third. Concurrency test in db/tests.
CREATE FUNCTION fn_guard_double_funding() RETURNS TRIGGER AS $$
DECLARE
    existing BIGINT;
BEGIN
    SELECT id INTO existing
      FROM commitments
     WHERE project_id = NEW.project_id AND status = 'active'
     LIMIT 1;

    IF existing IS NOT NULL THEN
        RAISE EXCEPTION 'project % already has active commitment %', NEW.project_id, existing
            USING ERRCODE = 'unique_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_guard_double_funding
    BEFORE INSERT ON commitments
    FOR EACH ROW EXECUTE FUNCTION fn_guard_double_funding();

-- ---------------------------------------------------------------- phase schedule

-- Recursive CTE generates the phase schedule from the agreement. Rounding
-- remainder lands on the final phase so SUM(phases) = commitment amount exactly.
CREATE FUNCTION fn_generate_phase_schedule() RETURNS TRIGGER AS $$
BEGIN
    WITH RECURSIVE phase_seq(n) AS (
        SELECT 1
        UNION ALL
        SELECT n + 1 FROM phase_seq WHERE n < NEW.num_phases
    )
    INSERT INTO fund_phases (commitment_id, phase_no, amount)
    SELECT NEW.id,
           n,
           CASE WHEN n < NEW.num_phases
                THEN round(NEW.amount / NEW.num_phases, 2)
                ELSE NEW.amount - round(NEW.amount / NEW.num_phases, 2) * (NEW.num_phases - 1)
           END
      FROM phase_seq;

    -- One milestone gates each phase.
    INSERT INTO milestones (project_id, commitment_id, phase_no, description, due_date)
    SELECT NEW.project_id, NEW.id, fp.phase_no,
           format('Phase %s deliverable', fp.phase_no),
           (CURRENT_DATE + (fp.phase_no * 90))::date
      FROM fund_phases fp
     WHERE fp.commitment_id = NEW.id;

    INSERT INTO fund_transactions (commitment_id, amount, txn_type, note)
    VALUES (NEW.id, NEW.amount, 'lock', 'funds locked on match confirmation');

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_generate_phase_schedule
    AFTER INSERT ON commitments
    FOR EACH ROW EXECUTE FUNCTION fn_generate_phase_schedule();

-- ---------------------------------------------------------------- milestone release

-- Fires ONLY on a verified transition. This is the mechanism the pitch calls
-- "no milestone proof, no release" -- the AI never reaches this code path.
CREATE FUNCTION fn_release_next_phase() RETURNS TRIGGER AS $$
DECLARE
    phase        fund_phases%ROWTYPE;
    remaining    INT;
BEGIN
    SELECT * INTO phase
      FROM fund_phases
     WHERE commitment_id = NEW.commitment_id AND phase_no = NEW.phase_no
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'no fund phase % for commitment %', NEW.phase_no, NEW.commitment_id;
    END IF;

    -- Idempotent: re-verifying an already released phase must not pay twice.
    IF phase.status <> 'locked' THEN
        RETURN NEW;
    END IF;

    UPDATE fund_phases
       SET status = 'released', released_at = now()
     WHERE id = phase.id;

    INSERT INTO fund_transactions (commitment_id, phase_id, amount, txn_type, note)
    VALUES (NEW.commitment_id, phase.id, phase.amount, 'release',
            format('phase %s released on verified milestone %s', NEW.phase_no, NEW.id));

    SELECT count(*) INTO remaining
      FROM fund_phases
     WHERE commitment_id = NEW.commitment_id AND status = 'locked';

    IF remaining = 0 THEN
        UPDATE commitments SET status = 'completed' WHERE id = NEW.commitment_id;
        UPDATE projects    SET status = 'closed'    WHERE id = NEW.project_id;
    ELSE
        UPDATE projects SET status = 'active'
         WHERE id = NEW.project_id AND status <> 'active';
    END IF;

    INSERT INTO audit_log (entity, entity_id, action, detail)
    VALUES ('milestone', NEW.id, 'phase_released',
            jsonb_build_object('phase_no', NEW.phase_no, 'amount', phase.amount));

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_release_next_phase
    AFTER UPDATE ON milestones
    FOR EACH ROW
    WHEN (OLD.verification_status IS DISTINCT FROM NEW.verification_status
          AND NEW.verification_status = 'verified')
    EXECUTE FUNCTION fn_release_next_phase();

-- Failed verification holds the phase and flags the project. Funds stay locked;
-- they are not silently forgotten and not released.
CREATE FUNCTION fn_hold_on_failed_verification() RETURNS TRIGGER AS $$
DECLARE
    phase fund_phases%ROWTYPE;
BEGIN
    SELECT * INTO phase
      FROM fund_phases
     WHERE commitment_id = NEW.commitment_id AND phase_no = NEW.phase_no
     FOR UPDATE;

    IF FOUND AND phase.status = 'locked' THEN
        UPDATE fund_phases SET status = 'held' WHERE id = phase.id;

        INSERT INTO fund_transactions (commitment_id, phase_id, amount, txn_type, note)
        VALUES (NEW.commitment_id, phase.id, phase.amount, 'hold',
                format('phase %s held on failed verification of milestone %s', NEW.phase_no, NEW.id));
    END IF;

    UPDATE projects SET status = 'flagged' WHERE id = NEW.project_id;

    INSERT INTO audit_log (entity, entity_id, action, detail)
    VALUES ('milestone', NEW.id, 'phase_held', jsonb_build_object('phase_no', NEW.phase_no));

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_hold_on_failed_verification
    AFTER UPDATE ON milestones
    FOR EACH ROW
    WHEN (OLD.verification_status IS DISTINCT FROM NEW.verification_status
          AND NEW.verification_status = 'failed')
    EXECUTE FUNCTION fn_hold_on_failed_verification();

-- ---------------------------------------------------------------- atomic commitment

-- The whole match->lock->record sequence as ONE operation. Row locks are taken
-- in a fixed order (company, then project) so concurrent callers cannot deadlock.
-- Any RAISE below rolls the entire function back: no half-committed state.
CREATE FUNCTION fn_commit_funds(
    p_company_id BIGINT,
    p_project_id BIGINT,
    p_match_id   BIGINT DEFAULT NULL,
    p_amount     NUMERIC DEFAULT NULL
) RETURNS BIGINT AS $$
DECLARE
    co            companies%ROWTYPE;
    pr            projects%ROWTYPE;
    v_amount      NUMERIC(16,2);
    v_commitment  BIGINT;
BEGIN
    SELECT * INTO co FROM companies WHERE id = p_company_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'company % not found', p_company_id;
    END IF;

    SELECT * INTO pr FROM projects WHERE id = p_project_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'project % not found', p_project_id;
    END IF;

    IF pr.status <> 'approved' THEN
        RAISE EXCEPTION 'project % is %, only approved projects can be funded',
            p_project_id, pr.status;
    END IF;

    v_amount := COALESCE(p_amount, pr.requested_amount);

    IF co.committed_budget + v_amount > co.mandated_csr_budget THEN
        RAISE EXCEPTION 'company % has % remaining, cannot commit %',
            p_company_id, co.mandated_csr_budget - co.committed_budget, v_amount;
    END IF;

    INSERT INTO commitments (match_id, company_id, project_id, amount, num_phases)
    VALUES (p_match_id, p_company_id, p_project_id, v_amount, pr.num_phases)
    RETURNING id INTO v_commitment;

    UPDATE companies
       SET committed_budget = committed_budget + v_amount
     WHERE id = p_company_id;

    UPDATE projects SET status = 'matched' WHERE id = p_project_id;

    INSERT INTO audit_log (entity, entity_id, action, detail)
    VALUES ('commitment', v_commitment, 'funds_locked',
            jsonb_build_object('company_id', p_company_id,
                               'project_id', p_project_id,
                               'amount', v_amount));

    RETURN v_commitment;
END;
$$ LANGUAGE plpgsql;
