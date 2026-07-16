-- Reactivation/response propensity score (P(books after contact)) from
-- velo_engage_booking_propensity, distinct from the no-show risk score.
ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS booking_propensity_score DOUBLE PRECISION;
