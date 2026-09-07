-- Migration 019: dental treatment-pathway prototype
-- (ve_connect_dental + ve_treatment_planner). PROTOTYPE — see
-- policies/dental_pathways/README.md's `status` field. No pathway loaded
-- from that directory has been clinically reviewed yet, so nothing written
-- to these tables should be surfaced to a real dentist as an authoritative
-- suggestion until that review happens.

-- Raw-ish procedure history pulled from a dental PMS (OpenDental today —
-- see services/ve_connect_dental/README.md). One row per procedure, kept
-- source-agnostic (the `source` column) in case a second PMS is added
-- later without a schema change.
CREATE TABLE IF NOT EXISTS dental_procedure_history (
    history_id        TEXT PRIMARY KEY,
    patient_id         TEXT NOT NULL,
    clinic_id            TEXT NOT NULL,
    source                 TEXT NOT NULL DEFAULT 'opendental',
    cdt_code                TEXT NOT NULL,
    tooth                     TEXT,
    surface                    TEXT,
    procedure_date               DATE,
    status                        TEXT,
    -- The source system's own ID for this procedure (OpenDental's ProcNum
    -- today) — the idempotency key for re-syncing the same procedure
    -- without duplicating it, paired with clinic_id+source since the same
    -- raw ID could theoretically recur across different clinics/PMS
    -- installations.
    raw_reference_id               TEXT NOT NULL,
    ingested_at                      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (clinic_id, source, raw_reference_id)
);
CREATE INDEX IF NOT EXISTS idx_dental_procedure_history_patient
    ON dental_procedure_history (patient_id, clinic_id);

-- Read model for the console — ve_treatment_planner's Temporal workflows
-- are the actual source of truth for a case's state; this table exists so
-- the console can query current state/suggestions without talking to
-- Temporal directly, kept in sync by the same activities that advance the
-- workflow (services/ve_treatment_planner/src/ve_treatment_planner/
-- activities.py).
--
-- One row per patient-CASE, not per patient — a patient can have more than
-- one concurrent, independent pathway instance (e.g. an endodontic case on
-- one tooth and a periodontal-maintenance case at the same time), which is
-- exactly why this is keyed by case_id and scoped by (patient_id, tooth),
-- not just patient_id alone.
CREATE TABLE IF NOT EXISTS patient_treatment_state (
    case_id                       TEXT PRIMARY KEY,
    patient_id                     TEXT NOT NULL,
    clinic_id                        TEXT NOT NULL,
    pathway_id                         TEXT NOT NULL,
    tooth                                TEXT,
    current_state                        TEXT NOT NULL,
    -- Populated only while there's more than one clinically valid next
    -- transition and nothing has been applied yet — see activities.py's
    -- advance_case(). NULL the rest of the time, including immediately
    -- after a single unambiguous transition auto-applies.
    suggested_next_states                    JSONB,
    workflow_id                                TEXT,
    entered_current_state_at                     TIMESTAMPTZ DEFAULT now(),
    updated_at                                     TIMESTAMPTZ DEFAULT now(),
    closed                                           BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_patient_treatment_state_patient
    ON patient_treatment_state (patient_id, clinic_id);

-- Full audit trail + the feedback-loop label source for a future
-- edge-ranker: every transition, whether auto-applied (accepted IS NULL,
-- unambiguous) or clinician-decided (accepted TRUE/FALSE + reason on
-- override). Append-only, never updated — this is deliberately Temporal's
-- workflow-history-adjacent record, not a mutable status field.
CREATE TABLE IF NOT EXISTS treatment_transition_log (
    log_id                    TEXT PRIMARY KEY,
    case_id                     TEXT NOT NULL REFERENCES patient_treatment_state(case_id),
    from_state                    TEXT,
    -- NULL while a suggestion is still pending a clinician's decision;
    -- populated once a transition is actually applied (auto or decided).
    to_state                        TEXT,
    suggested_state                    TEXT,
    accepted                             BOOLEAN,
    override_reason                        TEXT,
    decided_at                               TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_treatment_transition_log_case
    ON treatment_transition_log (case_id);
