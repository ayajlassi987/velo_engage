-- Distinguishes WhatsApp sends from the new Twilio SMS fallback channel.
ALTER TABLE outbound_messages
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'whatsapp';

-- Mirror existing WhatsApp consent to SMS so the fallback has something to
-- check against in this demo dataset. In production, SMS consent would be
-- captured explicitly, not inferred from WhatsApp consent.
INSERT INTO consent (patient_id, clinic_id, consent_class, channel, granted_at)
SELECT patient_id, clinic_id, consent_class, 'sms', granted_at
FROM consent
WHERE channel = 'whatsapp' AND revoked_at IS NULL
ON CONFLICT (patient_id, clinic_id, consent_class, channel) DO NOTHING;
