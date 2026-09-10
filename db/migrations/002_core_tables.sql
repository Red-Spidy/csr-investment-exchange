-- 002_core_tables.sql -- domain schema
-- Money is NUMERIC(16,2) throughout. Never floats: this table set moves funds.

CREATE TYPE project_status      AS ENUM ('pending','scoring','approved','flagged','rejected','matched','active','closed','terminated');
CREATE TYPE phase_status        AS ENUM ('locked','released','held','terminated');
CREATE TYPE verification_state  AS ENUM ('pending','submitted','verified','failed');
CREATE TYPE commitment_status   AS ENUM ('active','completed','cancelled');
CREATE TYPE risk_grade          AS ENUM ('A','B','C','D');

-- ---------------------------------------------------------------- actors

CREATE TABLE ngos (
    id               BIGSERIAL PRIMARY KEY,
    name             TEXT NOT NULL,
    registration_no  TEXT NOT NULL UNIQUE,
    sector           TEXT NOT NULL,
    state            TEXT,
    established_year INT  CHECK (established_year BETWEEN 1900 AND 2100),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE companies (
    id                  BIGSERIAL PRIMARY KEY,
    name                TEXT NOT NULL,
    cin                 TEXT NOT NULL UNIQUE,
    fy                  TEXT NOT NULL,
    avg_net_profit      NUMERIC(16,2) NOT NULL CHECK (avg_net_profit >= 0),
    -- Section 135: 2% of average net profit.
    mandated_csr_budget NUMERIC(16,2) NOT NULL CHECK (mandated_csr_budget >= 0),
    committed_budget    NUMERIC(16,2) NOT NULL DEFAULT 0 CHECK (committed_budget >= 0),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- A company can never commit more than it is mandated to spend. This single
    -- constraint is the last line of defence against over-commitment; the
    -- commitment transaction in 004 is the first.
    CONSTRAINT companies_within_budget CHECK (committed_budget <= mandated_csr_budget)
);

-- ---------------------------------------------------------------- projects

CREATE TABLE projects (
    id               BIGSERIAL PRIMARY KEY,
    ngo_id           BIGINT NOT NULL REFERENCES ngos(id) ON DELETE CASCADE,
    title            TEXT NOT NULL,
    proposal_text    TEXT NOT NULL,
    sector           TEXT NOT NULL,
    state            TEXT,
    requested_amount NUMERIC(16,2) NOT NULL CHECK (requested_amount > 0),
    duration_months  INT NOT NULL CHECK (duration_months > 0),
    num_phases       INT NOT NULL DEFAULT 3 CHECK (num_phases BETWEEN 1 AND 12),
    status           project_status NOT NULL DEFAULT 'pending',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_projects_status ON projects(status);
CREATE INDEX idx_projects_ngo    ON projects(ngo_id);

-- NLP module output. One row per project; embedding is of the CANONICAL text
-- (title + extracted fields + SDGs), not the raw proposal -- see plan.
CREATE TABLE project_extractions (
    project_id      BIGINT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    goals           JSONB NOT NULL DEFAULT '[]',
    target_metric   JSONB,
    beneficiaries   JSONB,
    geography       JSONB,
    budget_lines    JSONB NOT NULL DEFAULT '[]',
    duration_months INT,
    sdgs            INT[] NOT NULL DEFAULT '{}',
    sdg_confidence  JSONB NOT NULL DEFAULT '{}',
    red_flags       JSONB NOT NULL DEFAULT '[]',
    canonical_text  TEXT,
    embedding       VECTOR(384),
    raw_response    JSONB,          -- kept for audit + reproducibility
    model_version   TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    extracted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sdgs_in_range CHECK (sdgs <@ ARRAY[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17])
);

CREATE TABLE impact_predictions (
    project_id     BIGINT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    metric_name    TEXT NOT NULL,
    metric_unit    TEXT NOT NULL,
    predicted_value NUMERIC(10,4) NOT NULL,
    ci_low         NUMERIC(10,4) NOT NULL,   -- quantile 0.1
    ci_high        NUMERIC(10,4) NOT NULL,   -- quantile 0.9
    impact_norm    NUMERIC(5,4) NOT NULL CHECK (impact_norm BETWEEN 0 AND 1),
    model_version  TEXT NOT NULL,
    predicted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ci_ordered CHECK (ci_low <= predicted_value AND predicted_value <= ci_high)
);

-- Feature source for Isolation Forest, one row per NGO per financial year.
CREATE TABLE ngo_spending_history (
    id                    BIGSERIAL PRIMARY KEY,
    ngo_id                BIGINT NOT NULL REFERENCES ngos(id) ON DELETE CASCADE,
    fy                    TEXT NOT NULL,
    total_spend           NUMERIC(16,2) NOT NULL CHECK (total_spend >= 0),
    admin_expense_ratio   NUMERIC(5,4) NOT NULL CHECK (admin_expense_ratio BETWEEN 0 AND 1),
    burn_rate_vs_schedule NUMERIC(6,4) NOT NULL,
    category_mix_drift    NUMERIC(6,4) NOT NULL,
    round_number_freq     NUMERIC(5,4) NOT NULL CHECK (round_number_freq BETWEEN 0 AND 1),
    vendor_concentration  NUMERIC(5,4) NOT NULL CHECK (vendor_concentration BETWEEN 0 AND 1),
    report_latency_days   INT NOT NULL,
    cost_per_beneficiary  NUMERIC(12,2),
    is_anomalous_truth    BOOLEAN,  -- injected ground truth, evaluation only
    UNIQUE (ngo_id, fy)
);

CREATE TABLE fraud_scores (
    project_id    BIGINT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    ngo_id        BIGINT NOT NULL REFERENCES ngos(id) ON DELETE CASCADE,
    anomaly_score NUMERIC(5,4) NOT NULL CHECK (anomaly_score BETWEEN 0 AND 1),
    is_anomaly    BOOLEAN NOT NULL,
    model_version TEXT NOT NULL,
    scored_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Composite gate. Every component is stored so the UI can show the breakdown
-- and a reviewer can see exactly why a project was approved or held.
CREATE TABLE risk_grades (
    project_id       BIGINT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    impact_norm      NUMERIC(5,4) NOT NULL,
    fraud_score      NUMERIC(5,4) NOT NULL,
    sdg_confidence   NUMERIC(5,4) NOT NULL,
    ngo_track_record NUMERIC(5,4) NOT NULL,
    composite_score  NUMERIC(5,4) NOT NULL CHECK (composite_score BETWEEN 0 AND 1),
    grade            risk_grade NOT NULL,
    decision         project_status NOT NULL,
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- matching & funding

CREATE TABLE csr_rulebooks (
    id               BIGSERIAL PRIMARY KEY,
    company_id       BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    fy               TEXT NOT NULL,
    requirement_text TEXT NOT NULL,
    focus_areas      TEXT[] NOT NULL DEFAULT '{}',
    preferred_states TEXT[] NOT NULL DEFAULT '{}',
    target_sdgs      INT[]  NOT NULL DEFAULT '{}',
    min_budget       NUMERIC(16,2) NOT NULL DEFAULT 0,
    max_budget       NUMERIC(16,2) NOT NULL,
    embedding        VECTOR(384),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT budget_range_ordered CHECK (max_budget >= min_budget)
);

CREATE TABLE matches (
    id          BIGSERIAL PRIMARY KEY,
    rulebook_id BIGINT NOT NULL REFERENCES csr_rulebooks(id) ON DELETE CASCADE,
    company_id  BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    project_id  BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    similarity  NUMERIC(6,5) NOT NULL,
    match_score NUMERIC(6,5) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_matches_rulebook ON matches(rulebook_id);

CREATE TABLE commitments (
    id         BIGSERIAL PRIMARY KEY,
    match_id   BIGINT REFERENCES matches(id) ON DELETE SET NULL,
    company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    amount     NUMERIC(16,2) NOT NULL CHECK (amount > 0),
    num_phases INT NOT NULL CHECK (num_phases BETWEEN 1 AND 12),
    status     commitment_status NOT NULL DEFAULT 'active',
    locked_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- STRUCTURAL anti-double-funding: at most one active commitment per project.
-- A second concurrent commit fails here even if it slips past the guard trigger.
CREATE UNIQUE INDEX uniq_active_commitment_per_project
    ON commitments(project_id) WHERE status = 'active';

CREATE TABLE fund_phases (
    id            BIGSERIAL PRIMARY KEY,
    commitment_id BIGINT NOT NULL REFERENCES commitments(id) ON DELETE CASCADE,
    phase_no      INT NOT NULL CHECK (phase_no > 0),
    amount        NUMERIC(16,2) NOT NULL CHECK (amount > 0),
    status        phase_status NOT NULL DEFAULT 'locked',
    released_at   TIMESTAMPTZ,
    UNIQUE (commitment_id, phase_no)
);

CREATE TABLE milestones (
    id                  BIGSERIAL PRIMARY KEY,
    project_id          BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    commitment_id       BIGINT NOT NULL REFERENCES commitments(id) ON DELETE CASCADE,
    phase_no            INT NOT NULL CHECK (phase_no > 0),
    description         TEXT NOT NULL,
    due_date            DATE,
    reported_at         TIMESTAMPTZ,
    evidence_uri        TEXT,
    reported_metric     NUMERIC(12,4),
    verification_status verification_state NOT NULL DEFAULT 'pending',
    verified_by         TEXT,
    verified_at         TIMESTAMPTZ,
    UNIQUE (commitment_id, phase_no)
);

-- Append-only ledger. Never UPDATE or DELETE a row here.
CREATE TABLE fund_transactions (
    id            BIGSERIAL PRIMARY KEY,
    commitment_id BIGINT NOT NULL REFERENCES commitments(id) ON DELETE CASCADE,
    phase_id      BIGINT REFERENCES fund_phases(id) ON DELETE SET NULL,
    amount        NUMERIC(16,2) NOT NULL,
    txn_type      TEXT NOT NULL CHECK (txn_type IN ('lock','release','hold','terminate','refund')),
    note          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_fund_txn_commitment ON fund_transactions(commitment_id);

-- Monthly progress reported by the NGO -- the input to the window-function views.
CREATE TABLE impact_reports (
    id           BIGSERIAL PRIMARY KEY,
    project_id   BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    period_month DATE NOT NULL,
    metric_value NUMERIC(12,4) NOT NULL,
    reported_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, period_month)
);

CREATE TABLE audit_log (
    id         BIGSERIAL PRIMARY KEY,
    entity     TEXT NOT NULL,
    entity_id  BIGINT NOT NULL,
    action     TEXT NOT NULL,
    detail     JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
