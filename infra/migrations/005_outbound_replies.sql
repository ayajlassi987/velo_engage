ALTER TABLE outbound_messages
    ADD COLUMN IF NOT EXISTS replied BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS replied_at TIMESTAMPTZ;

-- Attribute each existing inbound reply to the latest message sent to that number.
WITH matched_replies AS (
    SELECT match.wa_message_id, MIN(i.received_at) AS replied_at
    FROM inbound_messages i
    CROSS JOIN LATERAL (
        SELECT om.wa_message_id
        FROM outbound_messages om
        WHERE regexp_replace(om.recipient_e164, '\D', '', 'g') =
              regexp_replace(i.from_number, '\D', '', 'g')
          AND om.sent_at <= i.received_at
          AND om.sent_at >= i.received_at - INTERVAL '30 days'
        ORDER BY om.sent_at DESC
        LIMIT 1
    ) match
    GROUP BY match.wa_message_id
)
UPDATE outbound_messages om
SET replied = TRUE,
    replied_at = COALESCE(om.replied_at, matched_replies.replied_at),
    updated_at = now()
FROM matched_replies
WHERE om.wa_message_id = matched_replies.wa_message_id;
