-- Migration 018: add the STAGE1_FEATURES columns ml/registry/scorer.py has
-- always required but patient_features never had — until now, _feature_row()
-- silently substituted its DEFAULTS constant for every one of these on every
-- score, for every patient (see scorer.py's DEFAULTS dict; same values used
-- here so a freshly-added row scores identically to before this migration
-- until refresh_historical_features() computes a real value).
--
-- provider_noshow_rate, provider_schedule_change, and temp_above_45c are
-- NOT computable from this schema (no provider entity, no scheduling-change
-- event, no weather integration) and stay fixed at their DEFAULTS value
-- forever — added here only so the column exists and the model's feature
-- contract is complete, not because they're ever recomputed.
-- hist_late_cancel_count_90d is similarly always 0: bookings.status only
-- ever transitions booked -> attended (see
-- ve_measure.booking_listener.record_booking), there is no distinct
-- cancellation event type in this system to count.

ALTER TABLE patient_features
  ADD COLUMN IF NOT EXISTS lead_time_days_log         FLOAT   DEFAULT 2.08,
  ADD COLUMN IF NOT EXISTS hour_bucket                TEXT    DEFAULT 'morning',
  ADD COLUMN IF NOT EXISTS is_followup                INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS provider_noshow_rate       FLOAT   DEFAULT 0.10,
  ADD COLUMN IF NOT EXISTS provider_schedule_change   INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS temp_above_45c             INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS hist_noshow_rate_90d       FLOAT   DEFAULT 0.15,
  ADD COLUMN IF NOT EXISTS hist_noshow_rate_365d      FLOAT   DEFAULT 0.15,
  ADD COLUMN IF NOT EXISTS hist_noshow_count_90d      INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS hist_kept_count_90d        INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS hist_late_cancel_count_90d INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS days_since_last_noshow     INTEGER DEFAULT 365,
  ADD COLUMN IF NOT EXISTS days_since_last_kept       INTEGER DEFAULT 365,
  ADD COLUMN IF NOT EXISTS hist_wa_confirm_rate       FLOAT   DEFAULT 0.5,
  ADD COLUMN IF NOT EXISTS hist_avg_reply_latency_min FLOAT   DEFAULT 60.0;
