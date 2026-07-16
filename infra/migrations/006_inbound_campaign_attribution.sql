WITH matched_inbound AS (
    SELECT i.inbound_id, outbound.campaign_id, outbound.patient_id
    FROM inbound_messages i
    CROSS JOIN LATERAL (
        SELECT om.campaign_id, om.patient_id
        FROM outbound_messages om
        WHERE regexp_replace(om.recipient_e164, '\D', '', 'g') =
              regexp_replace(i.from_number, '\D', '', 'g')
          AND om.campaign_id IS NOT NULL
          AND om.sent_at <= i.received_at
          AND om.sent_at >= i.received_at - INTERVAL '30 days'
        ORDER BY om.sent_at DESC
        LIMIT 1
    ) outbound
    WHERE i.campaign_id IS NULL
)
UPDATE inbound_messages i
SET campaign_id = matched_inbound.campaign_id,
    patient_id = matched_inbound.patient_id
FROM matched_inbound
WHERE i.inbound_id = matched_inbound.inbound_id;

INSERT INTO outcomes (campaign_id, patient_id, replied)
SELECT DISTINCT campaign_id, patient_id, TRUE
FROM inbound_messages
WHERE campaign_id IS NOT NULL AND patient_id IS NOT NULL
ON CONFLICT (campaign_id) DO UPDATE SET
    replied = TRUE,
    recorded_at = now();
