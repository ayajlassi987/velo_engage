-- priority_score x booking_propensity_score, persisted so dispatch ordering
-- (which re-queries by campaign_id, losing any in-memory sort order) can
-- still pick the highest expected-value campaigns first under DISPATCH_LIMIT.
ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS expected_value_score DOUBLE PRECISION;
