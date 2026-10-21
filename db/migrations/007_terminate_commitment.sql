-- 007_terminate_commitment.sql
-- A failed milestone holds a phase, and until now nothing could end the hold: the
-- 'terminate' and 'refund' ledger types, the 'terminated' phase state and the
-- 'cancelled' commitment state existed but no code reached them. This adds the way
-- out, and closes two holes that would have trapped held money.

-- ---------------------------------------------------------------- completion

-- A held phase is still owed money, so it keeps the commitment open. Before, only
-- locked phases counted: verifying phase 3 while phase 2 sat held completed the
-- commitment and closed the project, and the held money could never be resolved.
-- A release also no longer flips a project back to active while a phase is held.
CREATE OR REPLACE FUNCTION fn_release_next_phase() RETURNS TRIGGER AS $$
DECLARE
    phase        fund_phases%ROWTYPE;
    outstanding  INT;
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

    SELECT count(*) INTO outstanding
      FROM fund_phases
     WHERE commitment_id = NEW.commitment_id AND status IN ('locked', 'held');

    IF outstanding = 0 THEN
        UPDATE commitments SET status = 'completed' WHERE id = NEW.commitment_id;
        UPDATE projects    SET status = 'closed'    WHERE id = NEW.project_id;
    ELSIF NOT EXISTS (SELECT 1 FROM fund_phases
                       WHERE commitment_id = NEW.commitment_id AND status = 'held') THEN
        UPDATE projects SET status = 'active'
         WHERE id = NEW.project_id AND status <> 'active';
    END IF;

    INSERT INTO audit_log (entity, entity_id, action, detail)
    VALUES ('milestone', NEW.id, 'phase_released',
            jsonb_build_object('phase_no', NEW.phase_no, 'amount', phase.amount));

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------- closed commitments

-- Once a commitment is cancelled or completed its milestones are history. Without
-- this, failing a milestone of a cancelled commitment would flag a terminated project.
CREATE FUNCTION fn_guard_closed_commitment() RETURNS TRIGGER AS $$
DECLARE
    state commitment_status;
BEGIN
    SELECT status INTO state FROM commitments WHERE id = NEW.commitment_id;
    IF state <> 'active' THEN
        RAISE EXCEPTION 'commitment % is %, its milestones can no longer change',
            NEW.commitment_id, state;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_guard_closed_commitment
    BEFORE UPDATE OF verification_status ON milestones
    FOR EACH ROW
    WHEN (OLD.verification_status IS DISTINCT FROM NEW.verification_status)
    EXECUTE FUNCTION fn_guard_closed_commitment();

-- ---------------------------------------------------------------- terminate and refund

-- Ends an active commitment. Phases already released stay paid. Every phase still
-- locked or held is terminated and its money goes back to the company's budget,
-- each step written to the ledger. Returns the amount refunded.
--
-- Locks are taken company, milestones, phases, commitment, project. A verification
-- takes the milestone row, then the phase, commitment and project; fn_commit_funds takes
-- company then project. One order everywhere means a termination racing either of them
-- waits instead of deadlocking, and a verification that loses the race finds the
-- commitment cancelled and is refused by trg_guard_closed_commitment.
CREATE FUNCTION fn_terminate_commitment(
    p_commitment_id BIGINT,
    p_reason        TEXT,
    p_by            TEXT DEFAULT NULL
) RETURNS NUMERIC AS $$
DECLARE
    cm       commitments%ROWTYPE;
    ph       fund_phases%ROWTYPE;
    refunded NUMERIC(16,2) := 0;
BEGIN
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'a reason is required to terminate a commitment';
    END IF;

    SELECT * INTO cm FROM commitments WHERE id = p_commitment_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'commitment % not found', p_commitment_id;
    END IF;

    PERFORM 1 FROM companies WHERE id = cm.company_id FOR UPDATE;
    PERFORM 1 FROM milestones  WHERE commitment_id = cm.id ORDER BY id FOR UPDATE;
    PERFORM 1 FROM fund_phases WHERE commitment_id = cm.id ORDER BY id FOR UPDATE;
    SELECT * INTO cm FROM commitments WHERE id = p_commitment_id FOR UPDATE;
    PERFORM 1 FROM projects WHERE id = cm.project_id FOR UPDATE;

    IF cm.status <> 'active' THEN
        RAISE EXCEPTION 'commitment % is %, only active commitments can be terminated',
            cm.id, cm.status;
    END IF;

    FOR ph IN
        SELECT * FROM fund_phases
         WHERE commitment_id = cm.id AND status IN ('locked', 'held')
         ORDER BY phase_no
    LOOP
        UPDATE fund_phases SET status = 'terminated' WHERE id = ph.id;

        INSERT INTO fund_transactions (commitment_id, phase_id, amount, txn_type, note)
        VALUES (cm.id, ph.id, ph.amount, 'terminate',
                format('phase %s terminated: %s', ph.phase_no, btrim(p_reason)));

        refunded := refunded + ph.amount;
    END LOOP;

    IF refunded > 0 THEN
        INSERT INTO fund_transactions (commitment_id, amount, txn_type, note)
        VALUES (cm.id, refunded, 'refund', 'unreleased money returned to the company budget');

        UPDATE companies
           SET committed_budget = committed_budget - refunded
         WHERE id = cm.company_id;
    END IF;

    UPDATE commitments SET status = 'cancelled' WHERE id = cm.id;
    UPDATE projects    SET status = 'terminated' WHERE id = cm.project_id;

    INSERT INTO audit_log (entity, entity_id, action, detail)
    VALUES ('commitment', cm.id, 'commitment_terminated',
            jsonb_build_object('reason', btrim(p_reason),
                               'by', p_by,
                               'released', cm.amount - refunded,
                               'refunded', refunded));

    RETURN refunded;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------- leaderboard

-- "Funded" is money that reached the NGO. A cancelled commitment contributes only
-- the phases it released, not the part that went back to the company. Same columns
-- and types as 006, so the view is replaced in place.
CREATE OR REPLACE VIEW ngo_leaderboard AS
WITH project_totals AS (
    SELECT p.id     AS project_id,
           p.ngo_id,
           COALESCE((SELECT SUM(CASE WHEN cm.status = 'cancelled'
                                     THEN COALESCE((SELECT SUM(fp.amount) FROM fund_phases fp
                                                     WHERE fp.commitment_id = cm.id
                                                       AND fp.status = 'released'), 0)
                                     ELSE cm.amount END)
                       FROM commitments cm WHERE cm.project_id = p.id), 0) AS funded,
           COALESCE((SELECT SUM(ir.metric_value) FROM impact_reports ir WHERE ir.project_id = p.id), 0) AS impact
      FROM projects p
),
ngo_totals AS (
    SELECT n.id                               AS ngo_id,
           n.name                             AS ngo_name,
           n.sector,
           COUNT(pt.project_id)               AS project_count,
           COALESCE(SUM(pt.impact), 0)        AS total_impact,
           COALESCE(SUM(pt.funded), 0)        AS total_funded
      FROM ngos n
      LEFT JOIN project_totals pt ON pt.ngo_id = n.id
     GROUP BY n.id, n.name, n.sector
)
SELECT
    ngo_id,
    ngo_name,
    sector,
    project_count,
    total_impact,
    total_funded,
    CASE WHEN total_funded > 0
         THEN ROUND(total_impact / total_funded * 1000000, 4)
         ELSE NULL END                                     AS impact_per_million,
    DENSE_RANK() OVER (
        PARTITION BY sector
        ORDER BY CASE WHEN total_funded > 0
                      THEN total_impact / total_funded ELSE 0 END DESC
    )                                                      AS sector_rank,
    ROUND(PERCENT_RANK() OVER (
        ORDER BY CASE WHEN total_funded > 0
                      THEN total_impact / total_funded ELSE 0 END
    )::numeric, 4)                                         AS overall_percentile
  FROM ngo_totals;
