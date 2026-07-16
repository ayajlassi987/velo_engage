CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

CREATE TABLE IF NOT EXISTS staging_patients (
    patient_id       TEXT NOT NULL,
    clinic_id        TEXT NOT NULL,
    first_name       TEXT,
    last_name        TEXT,
    date_of_birth    DATE,
    sex              TEXT,
    phone_e164       TEXT,
    language         TEXT DEFAULT 'ar',
    condition_codes  TEXT[],
    last_visit_date  DATE,
    last_procedure_type TEXT,
    open_treatment_plan BOOLEAN DEFAULT FALSE,
    coverage_period_end_date DATE,
    ingested_at      TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (patient_id, clinic_id)
);

CREATE TABLE IF NOT EXISTS patient_features (
    patient_id               TEXT NOT NULL,
    clinic_id                TEXT NOT NULL,
    days_since_last_visit    INTEGER,
    visit_cadence_baseline   INTEGER DEFAULT 180,
    last_procedure_type      TEXT,
    last_procedure_date      DATE,
    open_treatment_plan_flag BOOLEAN DEFAULT FALSE,
    coverage_period_end_date DATE,
    condition_codes          TEXT[],
    age                      INTEGER,
    sex                      TEXT,
    clinical_recall_due_flag BOOLEAN NOT NULL DEFAULT FALSE,
    cross_specialty_gap_flag BOOLEAN NOT NULL DEFAULT FALSE,
    seasonal_event_eligible_flag BOOLEAN NOT NULL DEFAULT FALSE,
    engagement_drop_flag BOOLEAN NOT NULL DEFAULT FALSE,
    preference_match_flag BOOLEAN NOT NULL DEFAULT FALSE,
    care_gap_due_flag BOOLEAN NOT NULL DEFAULT FALSE,
    abandoned_booking_flag BOOLEAN NOT NULL DEFAULT FALSE,
    treatment_lifecycle_due_flag BOOLEAN NOT NULL DEFAULT FALSE,
    household_lifestage_eligible_flag BOOLEAN NOT NULL DEFAULT FALSE,
    contextual_trigger_flag BOOLEAN NOT NULL DEFAULT FALSE,
    slot_fill_eligible_flag BOOLEAN NOT NULL DEFAULT FALSE,
    quality_followup_due_flag BOOLEAN NOT NULL DEFAULT FALSE,
    as_of_timestamp          TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (patient_id, clinic_id)
);

CREATE TABLE IF NOT EXISTS consent (
    patient_id    TEXT NOT NULL,
    clinic_id     TEXT NOT NULL,
    consent_class TEXT NOT NULL,
    channel       TEXT NOT NULL,
    granted_at    TIMESTAMPTZ DEFAULT now(),
    revoked_at    TIMESTAMPTZ,
    PRIMARY KEY (patient_id, clinic_id, consent_class, channel)
);

CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_id TEXT PRIMARY KEY,
    patient_id     TEXT NOT NULL,
    clinic_id      TEXT NOT NULL,
    family         TEXT NOT NULL,
    consent_class  TEXT NOT NULL,
    priority_score FLOAT DEFAULT 0,
    triggered_at   TIMESTAMPTZ DEFAULT now(),
    rule_name      TEXT,
    rule_evidence  JSONB
);

CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id    TEXT PRIMARY KEY,
    opportunity_id TEXT NOT NULL,
    patient_id     TEXT NOT NULL,
    clinic_id      TEXT NOT NULL,
    family         TEXT NOT NULL,
    channel        TEXT DEFAULT 'whatsapp',
    treatment_arm  TEXT NOT NULL,
    template_id    TEXT,
    template_vars  JSONB,
    created_at     TIMESTAMPTZ DEFAULT now(),
    dispatched_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS outcomes (
    campaign_id TEXT PRIMARY KEY,
    patient_id  TEXT NOT NULL,
    delivered   BOOLEAN DEFAULT FALSE,
    read        BOOLEAN DEFAULT FALSE,
    replied     BOOLEAN DEFAULT FALSE,
    booked      BOOLEAN DEFAULT FALSE,
    attended    BOOLEAN DEFAULT FALSE,
    recorded_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wa_message_map (
    wa_message_id TEXT PRIMARY KEY,
    campaign_id   TEXT NOT NULL,
    patient_id    TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS outbound_messages (
    wa_message_id  TEXT PRIMARY KEY,
    campaign_id    TEXT REFERENCES campaigns(campaign_id),
    patient_id     TEXT,
    clinic_id      TEXT NOT NULL,
    recipient_e164 TEXT NOT NULL,
    template_name  TEXT,
    source         TEXT NOT NULL DEFAULT 'campaign',
    status         TEXT NOT NULL DEFAULT 'accepted',
    replied        BOOLEAN NOT NULL DEFAULT FALSE,
    replied_at     TIMESTAMPTZ,
    sent_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_outbound_messages_clinic_sent
    ON outbound_messages (clinic_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_outbound_messages_campaign
    ON outbound_messages (campaign_id);

CREATE TABLE IF NOT EXISTS inbound_messages (
    inbound_id TEXT PRIMARY KEY,
    wa_message_id TEXT,
    from_number TEXT NOT NULL,
    message_type TEXT,
    body TEXT,
    detected_intent TEXT,
    campaign_id TEXT REFERENCES campaigns(campaign_id),
    patient_id TEXT,
    received_at TIMESTAMPTZ DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_inbound_wa_message_id
    ON inbound_messages (wa_message_id)
    WHERE wa_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_inbound_received_at
    ON inbound_messages (received_at DESC);
