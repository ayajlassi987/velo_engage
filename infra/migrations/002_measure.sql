ALTER TABLE outcomes
    ADD COLUMN IF NOT EXISTS revenue NUMERIC(12, 2) NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS bookings (
    booking_id       TEXT PRIMARY KEY,
    patient_id       TEXT NOT NULL,
    clinic_id        TEXT NOT NULL,
    campaign_id      TEXT REFERENCES campaigns(campaign_id),
    appointment_date TIMESTAMPTZ NOT NULL,
    status           TEXT NOT NULL,
    source_event_id  TEXT UNIQUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bookings_attribution
    ON bookings (patient_id, clinic_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bookings_campaign
    ON bookings (campaign_id);

CREATE TABLE IF NOT EXISTS revenue_attributions (
    revenue_id      TEXT PRIMARY KEY,
    invoice_id      TEXT NOT NULL UNIQUE,
    procedure_id    TEXT,
    booking_id      TEXT REFERENCES bookings(booking_id),
    patient_id      TEXT NOT NULL,
    clinic_id       TEXT NOT NULL,
    campaign_id     TEXT REFERENCES campaigns(campaign_id),
    amount          NUMERIC(12, 2) NOT NULL CHECK (amount >= 0),
    currency        TEXT NOT NULL,
    paid            BOOLEAN NOT NULL DEFAULT FALSE,
    source_event_id TEXT UNIQUE,
    occurred_at     TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_revenue_campaign
    ON revenue_attributions (campaign_id, paid);
CREATE INDEX IF NOT EXISTS idx_revenue_booking
    ON revenue_attributions (booking_id);
