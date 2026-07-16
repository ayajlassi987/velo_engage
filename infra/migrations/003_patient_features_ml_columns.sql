-- Migration 003: add ML scoring columns to patient_features
-- These are the feature columns the CatBoost no-show model reads at scoring time.
-- All default to safe neutral values so existing rows are immediately scoreable.

ALTER TABLE patient_features
  ADD COLUMN IF NOT EXISTS prior_no_show_ratio        FLOAT   DEFAULT 0.15,
  ADD COLUMN IF NOT EXISTS lead_time_days             INTEGER DEFAULT 7,
  ADD COLUMN IF NOT EXISTS same_day_flag              INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS deposit_paid               INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS travel_time_minutes        FLOAT   DEFAULT 20.0,
  ADD COLUMN IF NOT EXISTS cancellation_history_ratio FLOAT   DEFAULT 0.10,
  ADD COLUMN IF NOT EXISTS vip_status                 INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS new_patient                INTEGER DEFAULT 1,
  ADD COLUMN IF NOT EXISTS urgency_score              FLOAT   DEFAULT 5.0,
  ADD COLUMN IF NOT EXISTS neighbourhood_ns_rate      FLOAT   DEFAULT 0.09,
  ADD COLUMN IF NOT EXISTS provider_effect            FLOAT   DEFAULT 0.0,
  ADD COLUMN IF NOT EXISTS consecutive_no_show_streak INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS time_of_day               TEXT    DEFAULT 'morning',
  ADD COLUMN IF NOT EXISTS specialty                 TEXT    DEFAULT 'dental',
  ADD COLUMN IF NOT EXISTS day_of_week               TEXT    DEFAULT 'Monday',
  ADD COLUMN IF NOT EXISTS treatment_stage           TEXT    DEFAULT 'consultation',
  ADD COLUMN IF NOT EXISTS is_ramadan                INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS is_public_holiday         INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS noshow_score              FLOAT;

-- Also add noshow_score to campaigns table for the audit trail
ALTER TABLE campaigns
  ADD COLUMN IF NOT EXISTS noshow_score FLOAT;