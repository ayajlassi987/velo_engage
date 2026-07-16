CREATE TABLE IF NOT EXISTS outbound_messages (
    wa_message_id  TEXT PRIMARY KEY,
    campaign_id    TEXT REFERENCES campaigns(campaign_id),
    patient_id     TEXT,
    clinic_id      TEXT NOT NULL,
    recipient_e164 TEXT NOT NULL,
    template_name  TEXT,
    source         TEXT NOT NULL DEFAULT 'campaign',
    status         TEXT NOT NULL DEFAULT 'accepted',
    sent_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_outbound_messages_clinic_sent
    ON outbound_messages (clinic_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_outbound_messages_campaign
    ON outbound_messages (campaign_id);
