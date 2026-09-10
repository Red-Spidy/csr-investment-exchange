-- 005_views_windows.sql
-- Window-function analytics. Every rolling/ranking number the UI shows is
-- computed here in SQL, not in Python.

-- Monthly ESG rollup per company: running total, MoM delta, 3-month rolling
-- average, and the company's percentile against its peers that month.
CREATE VIEW company_esg_timeline AS
WITH monthly AS (
    SELECT c.id                        AS company_id,
           c.name                      AS company_name,
           ir.period_month             AS month,
           SUM(ir.metric_value)        AS month_impact,
           COUNT(DISTINCT ir.project_id) AS active_projects
      FROM companies   c
      JOIN commitments cm ON cm.company_id = c.id
      JOIN impact_reports ir ON ir.project_id = cm.project_id
     GROUP BY c.id, c.name, ir.period_month
)
SELECT
    company_id,
    company_name,
    month,
    month_impact,
    active_projects,
    -- running cumulative impact since the company's first reported month
    SUM(month_impact) OVER w_running                       AS cumulative_impact,
    -- month-over-month change
    month_impact - LAG(month_impact) OVER w_ordered        AS mom_delta,
    LAG(month_impact) OVER w_ordered                       AS prev_month_impact,
    -- 3-month rolling average -- the "rolling ESG score"
    ROUND(AVG(month_impact) OVER w_rolling3, 4)            AS rolling_3mo_esg,
    -- where this company sits against all companies in the same month
    ROUND(PERCENT_RANK() OVER (
              PARTITION BY month ORDER BY month_impact
          )::numeric, 4)                                   AS peer_percentile
  FROM monthly
WINDOW
    w_running AS (PARTITION BY company_id ORDER BY month
                  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW),
    w_ordered AS (PARTITION BY company_id ORDER BY month),
    w_rolling3 AS (PARTITION BY company_id ORDER BY month
                   ROWS BETWEEN 2 PRECEDING AND CURRENT ROW);

-- NGO leaderboard: impact delivered per rupee, ranked inside each sector.
CREATE VIEW ngo_leaderboard AS
WITH ngo_totals AS (
    SELECT n.id      AS ngo_id,
           n.name    AS ngo_name,
           n.sector,
           COUNT(DISTINCT p.id)                    AS project_count,
           COALESCE(SUM(ir.metric_value), 0)       AS total_impact,
           COALESCE(SUM(cm.amount), 0)             AS total_funded
      FROM ngos n
      LEFT JOIN projects       p  ON p.ngo_id = n.id
      LEFT JOIN commitments    cm ON cm.project_id = p.id
      LEFT JOIN impact_reports ir ON ir.project_id = p.id
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

-- Flattened scoring view: one row per project with every AI component and the
-- funding position. This is what the review dashboard reads.
CREATE VIEW project_scorecard AS
SELECT
    p.id                AS project_id,
    p.title,
    p.status,
    p.sector,
    p.requested_amount,
    n.name              AS ngo_name,
    e.sdgs,
    e.goals,
    ip.predicted_value,
    ip.ci_low,
    ip.ci_high,
    ip.metric_unit,
    fs.anomaly_score,
    fs.is_anomaly,
    rg.composite_score,
    rg.grade,
    cm.id               AS commitment_id,
    cm.amount           AS committed_amount,
    COALESCE(SUM(fp.amount) FILTER (WHERE fp.status = 'released'), 0) AS released_amount,
    COALESCE(SUM(fp.amount) FILTER (WHERE fp.status = 'locked'),   0) AS locked_amount
  FROM projects p
  JOIN ngos n                  ON n.id  = p.ngo_id
  LEFT JOIN project_extractions e  ON e.project_id  = p.id
  LEFT JOIN impact_predictions  ip ON ip.project_id = p.id
  LEFT JOIN fraud_scores        fs ON fs.project_id = p.id
  LEFT JOIN risk_grades         rg ON rg.project_id = p.id
  LEFT JOIN commitments         cm ON cm.project_id = p.id AND cm.status = 'active'
  LEFT JOIN fund_phases         fp ON fp.commitment_id = cm.id
 GROUP BY p.id, p.title, p.status, p.sector, p.requested_amount, n.name,
          e.sdgs, e.goals, ip.predicted_value, ip.ci_low, ip.ci_high,
          ip.metric_unit, fs.anomaly_score, fs.is_anomaly,
          rg.composite_score, rg.grade, cm.id, cm.amount;

-- ---------------------------------------------------------------- matching

-- pgvector matching, fused with structured filters and the AI scores, ranked
-- and returned entirely inside the database. Weights mirror the plan:
--   0.60 semantic similarity + 0.25 predicted impact + 0.15 (1 - fraud)
CREATE FUNCTION fn_match_projects(p_rulebook_id BIGINT, p_top_k INT DEFAULT 5)
RETURNS TABLE (
    project_id       BIGINT,
    title            TEXT,
    ngo_name         TEXT,
    similarity       NUMERIC,
    impact_norm      NUMERIC,
    fraud_score      NUMERIC,
    match_score      NUMERIC,
    requested_amount NUMERIC
) AS $$
    SELECT
        p.id,
        p.title,
        n.name,
        ROUND((1 - (e.embedding <=> r.embedding))::numeric, 5)      AS similarity,
        COALESCE(ip.impact_norm, 0)                                 AS impact_norm,
        COALESCE(fs.anomaly_score, 0)                               AS fraud_score,
        ROUND((
              0.60 * (1 - (e.embedding <=> r.embedding))::numeric
            + 0.25 * COALESCE(ip.impact_norm, 0)
            + 0.15 * (1 - COALESCE(fs.anomaly_score, 0))
        ), 5)                                                       AS match_score,
        p.requested_amount
      FROM csr_rulebooks r
      JOIN project_extractions e ON e.embedding IS NOT NULL
      JOIN projects p            ON p.id = e.project_id
      JOIN ngos n                ON n.id = p.ngo_id
      LEFT JOIN impact_predictions ip ON ip.project_id = p.id
      LEFT JOIN fraud_scores       fs ON fs.project_id = p.id
     WHERE r.id = p_rulebook_id
       AND r.embedding IS NOT NULL
       AND p.status = 'approved'
       AND p.requested_amount BETWEEN r.min_budget AND r.max_budget
       AND (cardinality(r.preferred_states) = 0 OR p.state = ANY(r.preferred_states))
       AND (cardinality(r.target_sdgs)     = 0 OR e.sdgs && r.target_sdgs)
     ORDER BY match_score DESC
     LIMIT p_top_k;
$$ LANGUAGE sql STABLE;
