-- 10_risk_grade.sql -- the composite risk grade and the approval gate.
-- Each block RAISEs on failure, so a non-zero psql exit means a real regression.
-- Expected composites are worked by hand:
--   composite = 0.45*impact + 0.30*(1 - fraud_risk) + 0.15*sdg_confidence + 0.10*track_record
--   fraud_risk = clamp((anomaly_percentile - 0.80) / 0.20, 0, 1)
BEGIN;

CREATE TEMP TABLE t_ids (k TEXT PRIMARY KEY, id BIGINT);

-- fixture: two NGOs, one project per scenario, each with model evidence
DO $$
DECLARE
    n_clean BIGINT;
    n_risky BIGINT;
    pid     BIGINT;
    s       RECORD;
BEGIN
    INSERT INTO ngos (name, registration_no, sector, state) VALUES ('T Grade Clean', 'T-GRD-1', 'education', 'Goa')
        RETURNING id INTO n_clean;
    INSERT INTO ngos (name, registration_no, sector, state) VALUES ('T Grade Risky', 'T-GRD-2', 'education', 'Goa')
        RETURNING id INTO n_risky;
    INSERT INTO t_ids VALUES ('ngo_clean', n_clean), ('ngo_risky', n_risky);

    FOR s IN SELECT * FROM (VALUES
        -- key        ngo        impact  anomaly  flag   sdg confidences
        ('a_grade',   n_clean,   0.80,   0.50,    false, '{"4": 0.90, "5": 0.60}'),
        ('anomalous', n_risky,   0.80,   0.95,    true,  '{"4": 0.90}'),
        ('flag_wins', n_clean,   1.00,   0.91,    true,  '{"4": 1.00}'),
        ('no_sdg',    n_clean,   0.80,   0.50,    false, '{}')
    ) AS v(k, ngo, impact, anomaly, flag, conf)
    LOOP
        INSERT INTO projects (ngo_id, title, proposal_text, sector, state, requested_amount, duration_months, num_phases)
        VALUES (s.ngo, 'T ' || s.k, 'text', 'education', 'Goa', 400000, 12, 2) RETURNING id INTO pid;
        INSERT INTO t_ids VALUES (s.k, pid);
        INSERT INTO project_extractions (project_id, sdgs, sdg_confidence, target_metric, model_version, prompt_version)
        VALUES (pid, ARRAY[4], s.conf::jsonb, '{"name": "attendance_rate", "baseline": 48, "target": 57}', 'test', 'test');
        INSERT INTO impact_predictions (project_id, metric_name, metric_unit, predicted_value, ci_low, ci_high,
                                        impact_norm, model_version)
        VALUES (pid, 'attendance_rate', 'percentage_points', 5, 2, 7, s.impact, 'test');
        INSERT INTO fraud_scores (project_id, ngo_id, anomaly_score, is_anomaly, model_version)
        VALUES (pid, s.ngo, s.anomaly, s.flag, 'test');
    END LOOP;
END $$;

DO $$
DECLARE
    rg risk_grades%ROWTYPE;
    st project_status;
BEGIN
    -- impact 0.80, anomaly 0.50 -> risk 0, best SDG 0.90, new NGO -> track 0.5
    -- 0.36 + 0.30 + 0.135 + 0.05 = 0.845 -> A, approved
    PERFORM fn_grade_project((SELECT id FROM t_ids WHERE k = 'a_grade'));
    SELECT * INTO rg FROM risk_grades WHERE project_id = (SELECT id FROM t_ids WHERE k = 'a_grade');
    SELECT status INTO st FROM projects WHERE id = rg.project_id;
    IF rg.composite_score <> 0.8450 OR rg.grade <> 'A' OR rg.decision <> 'approved' OR st <> 'approved' THEN
        RAISE EXCEPTION 'FAIL 10a: got composite %, grade %, decision %, status %', rg.composite_score, rg.grade, rg.decision, st;
    END IF;
    IF rg.fraud_score <> 0 OR rg.sdg_confidence <> 0.90 OR rg.ngo_track_record <> 0.5 THEN
        RAISE EXCEPTION 'FAIL 10a: components stored wrong: fraud %, sdg %, track %', rg.fraud_score, rg.sdg_confidence, rg.ngo_track_record;
    END IF;
    RAISE NOTICE 'PASS 10a: composite computed from stored components, A approved';

    -- anomaly 0.95 -> risk (0.95-0.80)/0.20 = 0.75; 0.36 + 0.30*0.25 + 0.135 + 0.05 = 0.62 -> D, flagged
    PERFORM fn_grade_project((SELECT id FROM t_ids WHERE k = 'anomalous'));
    SELECT * INTO rg FROM risk_grades WHERE project_id = (SELECT id FROM t_ids WHERE k = 'anomalous');
    IF rg.composite_score <> 0.6200 OR rg.grade <> 'D' OR rg.decision <> 'flagged' OR rg.fraud_score <> 0.75 THEN
        RAISE EXCEPTION 'FAIL 10b: got composite %, grade %, decision %, risk %', rg.composite_score, rg.grade, rg.decision, rg.fraud_score;
    END IF;
    RAISE NOTICE 'PASS 10b: anomalous spending lowers the grade and routes to review';

    -- impact 1.0, anomaly 0.91 -> risk 0.55; 0.45 + 0.30*0.45 + 0.15 + 0.05 = 0.785 -> B
    -- B would be approved, but the fraud flag sends it to a person regardless.
    PERFORM fn_grade_project((SELECT id FROM t_ids WHERE k = 'flag_wins'));
    SELECT * INTO rg FROM risk_grades WHERE project_id = (SELECT id FROM t_ids WHERE k = 'flag_wins');
    IF rg.composite_score <> 0.7850 OR rg.grade <> 'B' OR rg.decision <> 'flagged' THEN
        RAISE EXCEPTION 'FAIL 10c: got composite %, grade %, decision %', rg.composite_score, rg.grade, rg.decision;
    END IF;
    RAISE NOTICE 'PASS 10c: a fraud flag overrides a passing grade';

    -- no SDG evidence -> 0; 0.36 + 0.30 + 0 + 0.05 = 0.71 -> C, flagged
    PERFORM fn_grade_project((SELECT id FROM t_ids WHERE k = 'no_sdg'));
    SELECT * INTO rg FROM risk_grades WHERE project_id = (SELECT id FROM t_ids WHERE k = 'no_sdg');
    IF rg.composite_score <> 0.7100 OR rg.grade <> 'C' OR rg.decision <> 'flagged' THEN
        RAISE EXCEPTION 'FAIL 10d: got composite %, grade %, decision %', rg.composite_score, rg.grade, rg.decision;
    END IF;
    RAISE NOTICE 'PASS 10d: missing SDG evidence counts as zero confidence';
END $$;

-- track record is the NGO's live verification history; regrading never touches a funded project
DO $$
DECLARE
    co      BIGINT;
    pid     BIGINT;
    c_id    BIGINT;
    n_risky BIGINT := (SELECT id FROM t_ids WHERE k = 'ngo_risky');
    n_clean BIGINT := (SELECT id FROM t_ids WHERE k = 'ngo_clean');
    st      project_status;
    n_rows  INT;
BEGIN
    IF fn_ngo_track_record(n_clean) <> 0.5 THEN
        RAISE EXCEPTION 'FAIL 10e: an NGO with no verified history should be neutral 0.5, got %', fn_ngo_track_record(n_clean);
    END IF;

    INSERT INTO companies (name, cin, fy, avg_net_profit, mandated_csr_budget)
    VALUES ('T Grade Co', 'T-GRD-CIN', 'FY24-25', 10000000, 10000000) RETURNING id INTO co;
    INSERT INTO projects (ngo_id, title, proposal_text, sector, state, requested_amount, duration_months, num_phases, status)
    VALUES (n_risky, 'T funded', 'text', 'education', 'Goa', 400000, 12, 4, 'approved') RETURNING id INTO pid;
    c_id := fn_commit_funds(co, pid, NULL, 400000);
    -- 3 of 4 milestones verified, 1 failed -> 0.75
    UPDATE milestones SET verification_status = 'verified' WHERE commitment_id = c_id AND phase_no IN (1, 2, 3);
    UPDATE milestones SET verification_status = 'failed' WHERE commitment_id = c_id AND phase_no = 4;
    IF fn_ngo_track_record(n_risky) <> 0.75 THEN
        RAISE EXCEPTION 'FAIL 10e: expected track record 0.75, got %', fn_ngo_track_record(n_risky);
    END IF;
    RAISE NOTICE 'PASS 10e: track record = verified share of decided milestones, neutral when none';

    -- The failed milestone held the funds and flagged this project. A regrade
    -- that flipped it back to approved would silently lift that hold.
    INSERT INTO project_extractions (project_id, sdgs, sdg_confidence, model_version, prompt_version)
    VALUES (pid, ARRAY[4], '{"4": 1.0}', 'test', 'test');
    INSERT INTO impact_predictions (project_id, metric_name, metric_unit, predicted_value, ci_low, ci_high, impact_norm, model_version)
    VALUES (pid, 'attendance_rate', 'percentage_points', 5, 2, 7, 1.0, 'test');
    INSERT INTO fraud_scores (project_id, ngo_id, anomaly_score, is_anomaly, model_version)
    VALUES (pid, n_risky, 0.10, false, 'test');
    PERFORM fn_grade_project(pid);
    PERFORM fn_grade_project(pid);
    SELECT status INTO st FROM projects WHERE id = pid;
    SELECT count(*) INTO n_rows FROM risk_grades WHERE project_id = pid;
    IF st <> 'flagged' OR n_rows <> 1 THEN
        RAISE EXCEPTION 'FAIL 10f: funded project status % (want flagged), % grade rows (want 1)', st, n_rows;
    END IF;
    RAISE NOTICE 'PASS 10f: regrading is idempotent and never changes a funded project''s status';
END $$;

-- no grade without evidence
DO $$
DECLARE
    pid BIGINT;
BEGIN
    INSERT INTO projects (ngo_id, title, proposal_text, sector, state, requested_amount, duration_months, num_phases)
    VALUES ((SELECT id FROM t_ids WHERE k = 'ngo_clean'), 'T unscored', 'text', 'education', 'Goa', 400000, 12, 2)
    RETURNING id INTO pid;
    BEGIN
        PERFORM fn_grade_project(pid);
        RAISE EXCEPTION 'FAIL 10g: graded a project with no model evidence';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE 'FAIL%' THEN RAISE; END IF;
    END;
    RAISE NOTICE 'PASS 10g: a project without impact and fraud evidence cannot be graded';
END $$;

-- a proposal with no measurable target cannot be approved by the machine
DO $$
DECLARE
    pid BIGINT;
    rg  risk_grades%ROWTYPE;
BEGIN
    INSERT INTO projects (ngo_id, title, proposal_text, sector, state, requested_amount, duration_months, num_phases)
    VALUES ((SELECT id FROM t_ids WHERE k = 'ngo_clean'), 'T vague', 'text', 'education', 'Goa', 400000, 12, 2)
    RETURNING id INTO pid;
    INSERT INTO project_extractions (project_id, sdgs, sdg_confidence, target_metric, model_version, prompt_version)
    VALUES (pid, ARRAY[4], '{"4": 1.0}', '{"name": "attendance_rate", "baseline": null, "target": null}', 'test', 'test');
    INSERT INTO impact_predictions (project_id, metric_name, metric_unit, predicted_value, ci_low, ci_high, impact_norm, model_version)
    VALUES (pid, 'outcome_score', 'normalised_0_1', 0.9, 0.5, 0.95, 0.9, 'test');
    INSERT INTO fraud_scores (project_id, ngo_id, anomaly_score, is_anomaly, model_version)
    VALUES (pid, (SELECT id FROM t_ids WHERE k = 'ngo_clean'), 0.10, false, 'test');
    -- 0.405 + 0.30 + 0.15 + 0.05 = 0.905 -> A on the numbers, but nothing measurable was promised
    PERFORM fn_grade_project(pid);
    SELECT * INTO rg FROM risk_grades WHERE project_id = pid;
    IF rg.grade <> 'A' OR rg.decision <> 'flagged' THEN
        RAISE EXCEPTION 'FAIL 10h: got grade %, decision % (want A, flagged)', rg.grade, rg.decision;
    END IF;
    RAISE NOTICE 'PASS 10h: no measurable target means a person decides, whatever the grade';
END $$;

-- manual review: a person settles what the grade routed to them, and that decision stands
DO $$
DECLARE
    a   BIGINT := (SELECT id FROM t_ids WHERE k = 'anomalous');    -- flagged by 10b
    d   BIGINT := (SELECT id FROM t_ids WHERE k = 'no_sdg');       -- flagged by 10d
    ok  BIGINT := (SELECT id FROM t_ids WHERE k = 'a_grade');      -- approved by 10a
    st  project_status;
    n   INT;
BEGIN
    PERFORM fn_review_project(a, true, 'T Reviewer', 'spending explained by a one-off grant');
    SELECT status INTO st FROM projects WHERE id = a;
    SELECT count(*) INTO n FROM project_reviews WHERE project_id = a AND reviewer = 'T Reviewer' AND decision = 'approved';
    IF st <> 'approved' OR n <> 1 THEN
        RAISE EXCEPTION 'FAIL 10i: approve after review gave status %, % review rows', st, n;
    END IF;

    -- Re-running the pipeline must not overturn a person's decision.
    PERFORM fn_grade_project(a);
    SELECT status INTO st FROM projects WHERE id = a;
    IF st <> 'approved' THEN
        RAISE EXCEPTION 'FAIL 10i: regrading overturned a reviewer''s approval (now %)', st;
    END IF;

    PERFORM fn_review_project(d, false, 'T Reviewer', 'no evidence of SDG fit');
    SELECT status INTO st FROM projects WHERE id = d;
    IF st <> 'rejected' THEN
        RAISE EXCEPTION 'FAIL 10i: reject after review gave status %', st;
    END IF;
    RAISE NOTICE 'PASS 10i: a reviewer approves or rejects a flagged project, and regrading respects it';

    -- Only a flagged, unfunded project is open for review.
    BEGIN
        PERFORM fn_review_project(ok, false, 'T Reviewer', NULL);
        RAISE EXCEPTION 'FAIL 10j: reviewed a project that was not flagged';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE 'FAIL%' THEN RAISE; END IF;
    END;
    RAISE NOTICE 'PASS 10j: only flagged projects can be reviewed';
END $$;

ROLLBACK;
