-- 006_fix_leaderboard_fanout.sql
-- ngo_leaderboard joined commitments and impact_reports in one pass, so every
-- commitment row was repeated once per monthly report: the seeded 2,400,000
-- commitment with six reports showed as 14,400,000, and impact_per_million was
-- a sixth of the true value. Sum each project's funding and impact separately
-- first, then roll the projects up to the NGO. Same columns and types, so the
-- view can be replaced in place on an existing database.

CREATE OR REPLACE VIEW ngo_leaderboard AS
WITH project_totals AS (
    SELECT p.id     AS project_id,
           p.ngo_id,
           COALESCE((SELECT SUM(cm.amount)       FROM commitments    cm WHERE cm.project_id = p.id), 0) AS funded,
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
