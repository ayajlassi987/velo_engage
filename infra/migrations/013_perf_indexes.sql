-- Performance indexes — patient_features/opportunities/campaigns previously
-- had only their primary keys despite clinic_id being filtered constantly
-- (ve_console/main.py, ve_orchestrator/activities.py, feature_store.py) and
-- campaigns being filtered/sorted by treatment_arm, dispatched_at,
-- patient_id, expected_value_score everywhere. Cosmetic today at the real
-- patient count, but protects the already-large synthetic-history tables
-- (300k+ opportunity rows, 60k+ campaign rows) and any future real-patient
-- growth. All additive/reversible (IF NOT EXISTS, no DROP/ALTER) — safe to
-- run against live data.

CREATE INDEX IF NOT EXISTS idx_patient_features_clinic ON patient_features (clinic_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_clinic ON opportunities (clinic_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_patient ON opportunities (patient_id, clinic_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_clinic_dispatched ON campaigns (clinic_id, dispatched_at);
CREATE INDEX IF NOT EXISTS idx_campaigns_patient_clinic ON campaigns (patient_id, clinic_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_treatment_arm ON campaigns (treatment_arm);
CREATE INDEX IF NOT EXISTS idx_campaigns_expected_value ON campaigns (expected_value_score DESC NULLS LAST);

-- Partial index matching feature_store.py's exact WHERE clause (see that
-- file's fetch_patient_features) — a plain btree can't serve a NOT LIKE
-- predicate, but a partial index whose predicate matches the query lets
-- Postgres use it directly instead of a sequential scan over the full
-- ~20,000-row synthetic population every 5-minute cache miss.
CREATE INDEX IF NOT EXISTS idx_patient_features_real ON patient_features (clinic_id)
    WHERE patient_id NOT LIKE 'SYN%' AND patient_id NOT LIKE 'P0%';
