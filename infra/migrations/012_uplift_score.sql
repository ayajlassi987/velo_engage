-- Estimated individual treatment effect from the T-learner uplift model
-- (velo_engage_uplift_treated / velo_engage_uplift_control): how much of
-- this patient's booking likelihood is actually caused by contacting them.
ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS uplift_score DOUBLE PRECISION;
