-- Task 2: Clinical Note Intelligence (MedGemma + NemoGuard). Stores only
-- the structured extraction output, never raw clinical note text — see
-- PROJECT_STATUS.md for the retention decision (no encryption-at-rest or
-- audit-logging exists in this codebase for PHI, so raw note text is
-- discarded by the extraction service before this row is ever written).

CREATE TABLE IF NOT EXISTS clinical_extractions (
    extraction_id              TEXT PRIMARY KEY,
    patient_id                 TEXT NOT NULL,
    clinic_id                  TEXT NOT NULL,
    document_reference_id      TEXT NOT NULL,
    note_date                  DATE,
    diagnoses                  JSONB,
    medications                JSONB,
    procedures                 JSONB,
    follow_up_recommendations  JSONB,
    clinical_risks              JSONB,
    safety_check_passed        BOOLEAN NOT NULL,
    validation_flags           JSONB,
    extracted_at                TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_clinical_extractions_clinic ON clinical_extractions (clinic_id);
CREATE INDEX IF NOT EXISTS idx_clinical_extractions_patient ON clinical_extractions (patient_id, clinic_id);
