-- Predicted days-to-book from the survival/timing model (velo_engage_survival):
-- how long this patient profile is expected to take to convert after
-- contact. Informational/monitoring only for now — not yet blended into
-- expected_value_score, since combining a duration estimate into a
-- per-contact EV formula needs its own deliberate mathematical treatment
-- (e.g. discounting later conversions), which is a separate design
-- decision from training the model itself.
ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS survival_score DOUBLE PRECISION;
