-- 009: what an NGO says alongside its numbers, and a model's 1-5 rating of it.
--
-- Every monthly report and every milestone's evidence can carry the NGO's own words
-- (what happened, and how it knows). A rater -- Gemini, or deterministic rules when
-- no model is available -- scores them from 1 (low) to 5 (good) against the bar: the
-- share of the promised gain the project should have reached by now. The rating is
-- advice for the reviewer. Nothing reads it to move money: a phase is still paid only
-- when a person verifies its milestone (trg_release_next_phase).

ALTER TABLE impact_reports
    ADD COLUMN update_text   TEXT,
    ADD COLUMN rating        SMALLINT CHECK (rating BETWEEN 1 AND 5),
    ADD COLUMN rating_reason TEXT,
    ADD COLUMN rating_flags  TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN rated_by      TEXT,
    ADD COLUMN rated_at      TIMESTAMPTZ;

ALTER TABLE milestones
    ADD COLUMN update_text   TEXT,
    ADD COLUMN rating        SMALLINT CHECK (rating BETWEEN 1 AND 5),
    ADD COLUMN rating_reason TEXT,
    ADD COLUMN rating_flags  TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN rated_by      TEXT,
    ADD COLUMN rated_at      TIMESTAMPTZ;

-- How much a proposal promised, in its own units, or NULL when that cannot be known:
-- the distance from its starting value to its target. A target with no starting value
-- promises nothing measurable, except for measures that start from zero (hectares
-- planted, tonnes collected), where the target is the whole promise. The same rule as
-- promisedChange in web/src/lib/claim.ts.
CREATE FUNCTION fn_promised_gain(p_project_id BIGINT) RETURNS NUMERIC AS $$
    SELECT CASE
             WHEN t ->> 'target' IS NULL THEN NULL
             WHEN t ->> 'baseline' IS NOT NULL
               THEN abs((t ->> 'target')::numeric - (t ->> 'baseline')::numeric)
             WHEN t ->> 'unit' IN ('hectares', 'tonnes_per_month', 'percent_increase')
               THEN (t ->> 'target')::numeric
           END
      FROM (SELECT target_metric AS t FROM project_extractions WHERE project_id = p_project_id) x
$$ LANGUAGE sql STABLE;
