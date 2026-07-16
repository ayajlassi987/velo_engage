-- Predicted E[revenue | reactivate] from velo_engage_value_amount, and the
-- full expected_value_score now folds it in: priority_score (appropriateness)
-- x booking_propensity_score (P(reactivate)) x value_score (E[revenue]).
ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS value_score DOUBLE PRECISION;
