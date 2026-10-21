-- 008_risk_grade.sql -- the composite risk grade and the approval gate.
--
-- The models write evidence (project_extractions, impact_predictions,
-- fraud_scores); this function decides. No model is in the approval path.
--
--   composite = 0.45 * impact          predicted share of the claim delivered (XGBoost)
--             + 0.30 * (1 - fraud_risk) NGO spending anomaly (Isolation Forest)
--             + 0.15 * sdg_confidence  best SDG confidence (BERT)
--             + 0.10 * track_record    the NGO's live verification history
--
-- The anomaly score is a percentile against training NGOs, so an ordinary NGO
-- sits anywhere from 0 to 0.8. Used raw, that spread swamped the impact signal
-- (grades A and B delivered the same). fraud_risk is zero for the 80% most
-- ordinary NGOs and rises to 1 at the most anomalous; it is 0.5 at the review
-- flag (top 10%).
--
-- Grade cut-offs were set on the synthetic VAL split (A = top 30%, B next 30%,
-- C next 25%) and checked once on TEST: A delivered 0.78 of its claims, B 0.63,
-- C 0.58, D 0.46, and all 11 projects of fraudulent NGOs landed in D. See
-- ml/pipeline/README.md.
--
-- Decision: A or B, no fraud flag, and a measurable target -> approved;
-- everything else goes to a person ('flagged'). Nothing is rejected
-- automatically. The target rule exists because a proposal that promises
-- nothing measurable still gets an impact score (a share of an unknown claim),
-- and on the numbers alone the vague demo proposal graded A.

-- A person's decision on a project the grade sent to review. It stands: a
-- later regrade updates the evidence but never overturns it.
CREATE TABLE project_reviews (
    project_id  BIGINT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    decision    project_status NOT NULL CHECK (decision IN ('approved', 'rejected')),
    reviewer    TEXT NOT NULL,
    note        TEXT,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE FUNCTION fn_fraud_risk(p_anomaly NUMERIC) RETURNS NUMERIC AS $$
    SELECT LEAST(GREATEST((p_anomaly - 0.80) / 0.20, 0), 1)
$$ LANGUAGE sql IMMUTABLE;

-- Share of the NGO's decided milestones that passed verification. An NGO with
-- no decided milestone yet is neutral, not penalised.
CREATE FUNCTION fn_ngo_track_record(p_ngo_id BIGINT) RETURNS NUMERIC AS $$
    SELECT COALESCE(
        ROUND(AVG(CASE WHEN m.verification_status = 'verified' THEN 1.0 ELSE 0.0 END), 4),
        0.5)
      FROM milestones m
      JOIN projects p ON p.id = m.project_id
     WHERE p.ngo_id = p_ngo_id
       AND m.verification_status IN ('verified', 'failed')
$$ LANGUAGE sql STABLE;

CREATE FUNCTION fn_grade_project(p_project_id BIGINT) RETURNS risk_grade AS $$
DECLARE
    pr          projects%ROWTYPE;
    v_impact    NUMERIC;
    v_anomaly   NUMERIC;
    v_flag      BOOLEAN;
    v_sdg       NUMERIC;
    v_track     NUMERIC;
    v_risk      NUMERIC;
    v_composite NUMERIC;
    v_grade     risk_grade;
    v_decision  project_status;
    v_target    BOOLEAN;
BEGIN
    SELECT * INTO pr FROM projects WHERE id = p_project_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'project % not found', p_project_id;
    END IF;

    SELECT impact_norm INTO v_impact FROM impact_predictions WHERE project_id = p_project_id;
    SELECT anomaly_score, is_anomaly INTO v_anomaly, v_flag FROM fraud_scores WHERE project_id = p_project_id;
    IF v_impact IS NULL OR v_anomaly IS NULL THEN
        RAISE EXCEPTION 'project % has not been scored: impact and fraud evidence are both required',
            p_project_id;
    END IF;

    SELECT (e.target_metric ->> 'target') IS NOT NULL INTO v_target
      FROM project_extractions e WHERE e.project_id = p_project_id;

    SELECT COALESCE(MAX(c.value::numeric), 0) INTO v_sdg
      FROM project_extractions e, jsonb_each_text(e.sdg_confidence) AS c
     WHERE e.project_id = p_project_id;

    v_track     := fn_ngo_track_record(pr.ngo_id);
    v_risk      := ROUND(fn_fraud_risk(v_anomaly), 4);
    v_composite := ROUND(0.45 * v_impact + 0.30 * (1 - v_risk) + 0.15 * v_sdg + 0.10 * v_track, 4);
    v_grade     := CASE WHEN v_composite >= 0.84 THEN 'A'
                        WHEN v_composite >= 0.77 THEN 'B'
                        WHEN v_composite >= 0.69 THEN 'C'
                        ELSE 'D' END;
    v_decision  := CASE WHEN v_grade IN ('A', 'B') AND NOT v_flag AND COALESCE(v_target, false)
                        THEN 'approved' ELSE 'flagged' END;

    -- fraud_score stores the risk the composite used, so the row reproduces it.
    INSERT INTO risk_grades (project_id, impact_norm, fraud_score, sdg_confidence, ngo_track_record,
                             composite_score, grade, decision)
    VALUES (p_project_id, v_impact, v_risk, v_sdg, v_track, v_composite, v_grade, v_decision)
    ON CONFLICT (project_id) DO UPDATE SET
        impact_norm      = EXCLUDED.impact_norm,
        fraud_score      = EXCLUDED.fraud_score,
        sdg_confidence   = EXCLUDED.sdg_confidence,
        ngo_track_record = EXCLUDED.ngo_track_record,
        composite_score  = EXCLUDED.composite_score,
        grade            = EXCLUDED.grade,
        decision         = EXCLUDED.decision,
        computed_at      = now();

    -- A grade moves a project into or out of the matching pool only before any
    -- money is committed. A funded project's status belongs to the milestone
    -- triggers: regrading one that failed verification must not lift its hold.
    UPDATE projects SET status = v_decision
     WHERE id = p_project_id
       AND status IN ('pending', 'scoring', 'approved', 'flagged')
       AND NOT EXISTS (SELECT 1 FROM commitments c WHERE c.project_id = p_project_id)
       AND NOT EXISTS (SELECT 1 FROM project_reviews r WHERE r.project_id = p_project_id);

    INSERT INTO audit_log (entity, entity_id, action, detail)
    VALUES ('project', p_project_id, 'graded',
            jsonb_build_object('grade', v_grade, 'composite', v_composite, 'decision', v_decision,
                               'fraud_flag', v_flag, 'measurable_target', COALESCE(v_target, false)));

    RETURN v_grade;
END;
$$ LANGUAGE plpgsql;

-- The manual review the grade routes projects to. Only a flagged project with
-- no money committed is open for review; the reviewer approves it into the
-- matching pool or rejects it, and the reason is kept.
CREATE FUNCTION fn_review_project(p_project_id BIGINT, p_approve BOOLEAN, p_reviewer TEXT,
                                  p_note TEXT DEFAULT NULL) RETURNS project_status AS $$
DECLARE
    pr         projects%ROWTYPE;
    v_decision project_status := CASE WHEN p_approve THEN 'approved' ELSE 'rejected' END;
BEGIN
    SELECT * INTO pr FROM projects WHERE id = p_project_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'project % not found', p_project_id;
    END IF;
    IF pr.status <> 'flagged' OR EXISTS (SELECT 1 FROM commitments c WHERE c.project_id = p_project_id) THEN
        RAISE EXCEPTION 'project % is %, only a flagged project with no commitment can be reviewed',
            p_project_id, pr.status;
    END IF;
    IF coalesce(trim(p_reviewer), '') = '' THEN
        RAISE EXCEPTION 'a review needs a reviewer';
    END IF;

    INSERT INTO project_reviews (project_id, decision, reviewer, note)
    VALUES (p_project_id, v_decision, p_reviewer, p_note)
    ON CONFLICT (project_id) DO UPDATE SET decision = EXCLUDED.decision, reviewer = EXCLUDED.reviewer,
        note = EXCLUDED.note, reviewed_at = now();
    UPDATE projects SET status = v_decision WHERE id = p_project_id;
    INSERT INTO audit_log (entity, entity_id, action, detail)
    VALUES ('project', p_project_id, 'reviewed',
            jsonb_build_object('decision', v_decision, 'reviewer', p_reviewer, 'note', p_note));
    RETURN v_decision;
END;
$$ LANGUAGE plpgsql;
