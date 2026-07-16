CREATE TABLE IF NOT EXISTS inbound_messages (
    inbound_id     TEXT PRIMARY KEY,
    wa_message_id  TEXT,
    from_number    TEXT NOT NULL,
    message_type   TEXT,
    body           TEXT,
    detected_intent TEXT,
    campaign_id    TEXT REFERENCES campaigns(campaign_id),
    patient_id     TEXT,
    received_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE inbound_messages
    ADD COLUMN IF NOT EXISTS campaign_id TEXT REFERENCES campaigns(campaign_id),
    ADD COLUMN IF NOT EXISTS patient_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_inbound_wa_message_id
    ON inbound_messages (wa_message_id)
    WHERE wa_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_inbound_received_at
    ON inbound_messages (received_at DESC);
