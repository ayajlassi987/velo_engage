import psycopg2
import os
import sys
from datetime import datetime

sys.path.insert(0, ".")
from libs.ve_clients.vault_client import get_secret


def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "velodb"),
        user=get_secret("postgres", "user", "DB_USER") or "velo",
        password=get_secret("postgres", "password", "DB_PASSWORD") or "velo_secret",
    )


def mark_dispatched(campaign_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE campaigns SET dispatched_at = %s WHERE campaign_id = %s",
        (datetime.utcnow(), campaign_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def is_campaign_dispatched(campaign_id: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT dispatched_at IS NOT NULL FROM campaigns WHERE campaign_id = %s",
        (campaign_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return bool(row and row[0])


def upsert_outcome(campaign_id: str, patient_id: str, **fields):
    """This function is called repeatedly as a campaign progresses through
    stages (delivered, then read, then replied, ...) — each call only sets
    the flags true for stages that have actually happened *so far*. The
    per-stage _at columns use CASE WHEN on the INSERT side and COALESCE on
    the UPDATE side so each one is only ever set once, the first time that
    stage becomes true — a naive `= now()` on every call would clobber
    earlier stages' real timing with whatever the latest call happened to
    be, which is exactly the bug that made duration/timing analysis
    impossible before this was added (see infra/migrations/015)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO outcomes
          (campaign_id, patient_id, delivered, read, replied, booked, attended,
           delivered_at, read_at, replied_at, booked_at, attended_at)
        VALUES
          (%(campaign_id)s, %(patient_id)s, %(delivered)s, %(read)s,
           %(replied)s, %(booked)s, %(attended)s,
           CASE WHEN %(delivered)s THEN now() END,
           CASE WHEN %(read)s THEN now() END,
           CASE WHEN %(replied)s THEN now() END,
           CASE WHEN %(booked)s THEN now() END,
           CASE WHEN %(attended)s THEN now() END)
        ON CONFLICT (campaign_id) DO UPDATE
          SET delivered  = outcomes.delivered OR EXCLUDED.delivered,
              read       = outcomes.read OR EXCLUDED.read,
              replied    = outcomes.replied OR EXCLUDED.replied,
              booked     = outcomes.booked OR EXCLUDED.booked,
              attended   = outcomes.attended OR EXCLUDED.attended,
              delivered_at = COALESCE(outcomes.delivered_at, EXCLUDED.delivered_at),
              read_at      = COALESCE(outcomes.read_at, EXCLUDED.read_at),
              replied_at   = COALESCE(outcomes.replied_at, EXCLUDED.replied_at),
              booked_at    = COALESCE(outcomes.booked_at, EXCLUDED.booked_at),
              attended_at  = COALESCE(outcomes.attended_at, EXCLUDED.attended_at),
              recorded_at = now()
    """, {
        "campaign_id": campaign_id,
        "patient_id": patient_id,
        "delivered": bool(fields.get("delivered", False)),
        "read": bool(fields.get("read", False)),
        "replied": bool(fields.get("replied", False)),
        "booked": bool(fields.get("booked", False)),
        "attended": bool(fields.get("attended", False)),
    })
    conn.commit()
    cur.close()
    conn.close()


def get_patient_phone(patient_id: str, clinic_id: str) -> str | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT phone_e164 FROM staging_patients WHERE patient_id=%s AND clinic_id=%s",
        (patient_id, clinic_id),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None


def get_patient_name(patient_id: str, clinic_id: str) -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT first_name FROM staging_patients WHERE patient_id=%s AND clinic_id=%s",
        (patient_id, clinic_id),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else patient_id


def save_message_id(wa_message_id: str, campaign_id: str, patient_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO wa_message_map (wa_message_id, campaign_id, patient_id)
        VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
    """, (wa_message_id, campaign_id, patient_id))
    conn.commit()
    cur.close()
    conn.close()


def save_outbound_message(
    wa_message_id: str,
    recipient_e164: str,
    clinic_id: str,
    template_name: str,
    source: str,
    campaign_id: str | None = None,
    patient_id: str | None = None,
    channel: str = "whatsapp",
) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO outbound_messages
          (wa_message_id, campaign_id, patient_id, clinic_id, recipient_e164,
           template_name, source, status, channel)
        VALUES (%s,%s,%s,%s,%s,%s,%s,'accepted',%s)
        ON CONFLICT (wa_message_id) DO UPDATE SET
          campaign_id=COALESCE(outbound_messages.campaign_id, EXCLUDED.campaign_id),
          patient_id=COALESCE(outbound_messages.patient_id, EXCLUDED.patient_id),
          recipient_e164=EXCLUDED.recipient_e164,
          template_name=EXCLUDED.template_name,
          updated_at=now()
        """,
        (
            wa_message_id, campaign_id, patient_id, clinic_id, recipient_e164,
            template_name, source, channel,
        ),
    )
    conn.commit()
    cur.close()
    conn.close()


def update_outbound_status(wa_message_id: str, status: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE outbound_messages
        SET status=CASE
              WHEN outbound_messages.status='read' THEN outbound_messages.status
              WHEN outbound_messages.status='delivered'
                   AND %s IN ('accepted','sent','failed')
                THEN outbound_messages.status
              WHEN outbound_messages.status='sent' AND %s='accepted'
                THEN outbound_messages.status
              ELSE %s
            END,
            updated_at=now()
        WHERE wa_message_id=%s
        """,
        (status, status, status, wa_message_id),
    )
    updated = cur.rowcount == 1
    conn.commit()
    cur.close()
    conn.close()
    return updated


def revoke_consent_by_phone(from_number: str) -> int:
    """Revoke WhatsApp consent for the patient behind the latest outbound send."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT patient_id, clinic_id
        FROM outbound_messages
        WHERE regexp_replace(recipient_e164, '\D', '', 'g') =
              regexp_replace(%s, '\D', '', 'g')
          AND patient_id IS NOT NULL
        ORDER BY sent_at DESC
        LIMIT 1
        """,
        (from_number,),
    )
    patient = cur.fetchone()
    if not patient:
        cur.execute(
            """
            SELECT patient_id, clinic_id
            FROM staging_patients
            WHERE regexp_replace(phone_e164, '\D', '', 'g') =
                  regexp_replace(%s, '\D', '', 'g')
            LIMIT 1
            """,
            (from_number,),
        )
        patient = cur.fetchone()
    revoked = 0
    if patient:
        cur.execute(
            """
            UPDATE consent
            SET revoked_at=COALESCE(revoked_at, now())
            WHERE patient_id=%s AND clinic_id=%s AND channel='whatsapp'
            """,
            patient,
        )
        revoked = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return revoked


def lookup_campaign_by_wa_id(wa_message_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT campaign_id, patient_id FROM wa_message_map WHERE wa_message_id=%s",
        (wa_message_id,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return (row[0], row[1]) if row else None


def get_sms_fallback_context(campaign_id: str) -> dict | None:
    """Everything needed to attempt an SMS fallback for a campaign whose
    WhatsApp delivery just failed: the patient's phone, the same rule
    evidence the WhatsApp template used, and the consent_class to check."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.patient_id, c.clinic_id, c.family, o.consent_class, o.rule_evidence,
               sp.phone_e164, COALESCE(sp.first_name, c.patient_id) AS patient_name
        FROM campaigns c
        JOIN opportunities o ON o.opportunity_id = c.opportunity_id
        JOIN staging_patients sp ON sp.patient_id = c.patient_id AND sp.clinic_id = c.clinic_id
        WHERE c.campaign_id = %s
        """,
        (campaign_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    patient_id, clinic_id, family, consent_class, rule_evidence, phone_e164, patient_name = row
    return {
        "patient_id": patient_id,
        "clinic_id": clinic_id,
        "family": family,
        "consent_class": consent_class,
        "rule_evidence": rule_evidence or {},
        "phone_e164": phone_e164,
        "patient_name": patient_name,
    }


def has_sms_consent(patient_id: str, clinic_id: str, consent_class: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1 FROM consent
        WHERE patient_id=%s AND clinic_id=%s AND consent_class=%s
          AND channel='sms' AND revoked_at IS NULL
        """,
        (patient_id, clinic_id, consent_class),
    )
    found = cur.fetchone() is not None
    cur.close()
    conn.close()
    return found


def save_inbound_message(
    inbound_id: str,
    from_number: str,
    message_type: str,
    body: str | None,
    detected_intent: str,
    received_at: datetime | None = None,
) -> bool:
    """Store one inbound message and attribute it to the latest outbound message."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT campaign_id, patient_id
        FROM outbound_messages
        WHERE regexp_replace(recipient_e164, '\D', '', 'g') =
              regexp_replace(%s, '\D', '', 'g')
          AND campaign_id IS NOT NULL
          AND sent_at <= COALESCE(%s, now())
          AND sent_at >= COALESCE(%s, now()) - INTERVAL '30 days'
        ORDER BY sent_at DESC
        LIMIT 1
        """,
        (from_number, received_at, received_at),
    )
    attribution = cur.fetchone()
    if not attribution:
        cur.execute(
            """
            SELECT c.campaign_id, c.patient_id
            FROM campaigns c
            JOIN staging_patients p
              ON p.patient_id=c.patient_id AND p.clinic_id=c.clinic_id
            WHERE regexp_replace(p.phone_e164, '\D', '', 'g') =
                  regexp_replace(%s, '\D', '', 'g')
              AND c.dispatched_at IS NOT NULL
            ORDER BY c.dispatched_at DESC, c.created_at DESC
            LIMIT 1
            """,
            (from_number,),
        )
        attribution = cur.fetchone()
    campaign_id, patient_id = attribution if attribution else (None, None)

    cur.execute(
        """
        INSERT INTO inbound_messages
          (inbound_id, wa_message_id, from_number, message_type, body,
           detected_intent, campaign_id, patient_id, received_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,COALESCE(%s,now()))
        ON CONFLICT (inbound_id) DO UPDATE SET
          campaign_id=COALESCE(inbound_messages.campaign_id, EXCLUDED.campaign_id),
          patient_id=COALESCE(inbound_messages.patient_id, EXCLUDED.patient_id)
        """,
        (
            inbound_id, inbound_id, from_number, message_type, body,
            detected_intent, campaign_id, patient_id, received_at,
        ),
    )
    inserted = cur.rowcount == 1
    if inserted:
        cur.execute(
            """
            UPDATE outbound_messages
            SET replied=TRUE,
                replied_at=COALESCE(replied_at, COALESCE(%s, now())),
                updated_at=now()
            WHERE wa_message_id = (
              SELECT wa_message_id
              FROM outbound_messages
              WHERE regexp_replace(recipient_e164, '\D', '', 'g') =
                    regexp_replace(%s, '\D', '', 'g')
                AND sent_at <= COALESCE(%s, now())
                AND sent_at >= COALESCE(%s, now()) - INTERVAL '30 days'
              ORDER BY sent_at DESC
              LIMIT 1
            )
            """,
            (received_at, from_number, received_at, received_at),
        )
    if inserted and campaign_id:
        cur.execute(
            """
            INSERT INTO outcomes (campaign_id, patient_id, replied, replied_at)
            VALUES (%s,%s,TRUE,COALESCE(%s,now()))
            ON CONFLICT (campaign_id) DO UPDATE SET
              replied=TRUE,
              replied_at=COALESCE(outcomes.replied_at, EXCLUDED.replied_at),
              recorded_at=now()
            """,
            (campaign_id, patient_id, received_at),
        )
    conn.commit()
    cur.close()
    conn.close()
    return inserted
