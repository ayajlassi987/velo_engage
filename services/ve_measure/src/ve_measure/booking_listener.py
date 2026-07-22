"""Consume booking and billing events and attribute them to campaigns."""

import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import nats
import psycopg2
from nats.js.api import AckPolicy, ConsumerConfig

for _candidate in (
    Path(__file__).resolve().parents[4] if len(Path(__file__).resolve().parents) > 4 else None,
    Path("/app"),
):
    if _candidate and (_candidate / "libs").is_dir():
        sys.path.insert(0, str(_candidate))
        break
from libs.ve_clients.vault_client import get_secret

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ATTRIBUTION_WINDOW_DAYS = int(os.getenv("ATTRIBUTION_WINDOW_DAYS", "30"))
BOOKING_EVENTS = {"AppointmentConfirmed", "AppointmentCompleted"}
REVENUE_EVENTS = {"Invoice", "Payment", "Procedure"}


def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "velodb"),
        user=get_secret("postgres", "user", "DB_USER") or "velo",
        password=get_secret("postgres", "password", "DB_PASSWORD") or "velo_secret",
    )


def apply_migrations() -> None:
    migration_path = Path(os.getenv("MEASURE_MIGRATION", "/app/migrations/002_measure.sql"))
    if not migration_path.exists():
        migration_path = Path(__file__).parents[4] / "infra/migrations/002_measure.sql"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(migration_path.read_text())
    logger.info("Measurement schema is ready")


def parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def event_parts(subject: str, payload: dict) -> tuple[str, str, dict, datetime]:
    data = payload.get("data", payload)
    event_type = payload.get("event_type") or payload.get("type") or subject.rsplit(".", 1)[-1]
    event_id = payload.get("event_id") or data.get("event_id") or str(uuid.uuid4())
    occurred_at = parse_time(payload.get("occurred_at") or data.get("occurred_at"))
    return event_type, event_id, data, occurred_at


def require(data: dict, *fields: str) -> None:
    missing = [field for field in fields if data.get(field) in (None, "")]
    if missing:
        raise ValueError(f"Missing required event fields: {', '.join(missing)}")


def find_campaign(cur, data: dict, occurred_at: datetime) -> str | None:
    explicit = data.get("campaign_id")
    if explicit:
        cur.execute(
            """
            SELECT campaign_id FROM campaigns
            WHERE campaign_id=%s AND patient_id=%s AND clinic_id=%s
            """,
            (explicit, data["patient_id"], data["clinic_id"]),
        )
        row = cur.fetchone()
        if row:
            return row[0]

    cur.execute(
        """
        SELECT campaign_id
        FROM campaigns
        WHERE patient_id=%s AND clinic_id=%s
          AND created_at <= %s
          AND created_at >= %s - (%s * interval '1 day')
        ORDER BY created_at DESC, dispatched_at DESC NULLS LAST, campaign_id
        LIMIT 1
        """,
        (data["patient_id"], data["clinic_id"], occurred_at, occurred_at, ATTRIBUTION_WINDOW_DAYS),
    )
    row = cur.fetchone()
    return row[0] if row else None


def record_booking(event_type: str, event_id: str, data: dict, occurred_at: datetime) -> None:
    require(data, "booking_id", "patient_id", "clinic_id")
    status = "attended" if event_type == "AppointmentCompleted" else "booked"

    with get_conn() as conn, conn.cursor() as cur:
        appointment_date = data.get("appointment_date")
        if not appointment_date:
            cur.execute(
                """
                SELECT appointment_date FROM bookings
                WHERE booking_id=%s AND patient_id=%s AND clinic_id=%s
                """,
                (data["booking_id"], data["patient_id"], data["clinic_id"]),
            )
            existing = cur.fetchone()
            if not existing:
                raise ValueError("AppointmentCompleted requires an existing booking or appointment_date")
            appointment_date = existing[0]
        campaign_id = find_campaign(cur, data, occurred_at)
        cur.execute(
            """
            INSERT INTO bookings
              (booking_id, patient_id, clinic_id, campaign_id, appointment_date,
               status, source_event_id, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (booking_id) DO UPDATE SET
              campaign_id=COALESCE(bookings.campaign_id, EXCLUDED.campaign_id),
              appointment_date=EXCLUDED.appointment_date,
              status=CASE WHEN EXCLUDED.status='attended' THEN 'attended' ELSE bookings.status END,
              updated_at=now()
            RETURNING campaign_id
            """,
            (
                data["booking_id"], data["patient_id"], data["clinic_id"], campaign_id,
                parse_time(appointment_date) if isinstance(appointment_date, str) else appointment_date,
                status, event_id, occurred_at,
            ),
        )
        attributed_campaign = cur.fetchone()[0]
        if attributed_campaign:
            # occurred_at is the real event time reported by the source system
            # (not now()) — using it here, rather than the time this handler
            # happened to run, means booked_at/attended_at reflect when the
            # patient actually booked/attended, which is what any
            # duration/timing analysis needs (see infra/migrations/015).
            # COALESCE on conflict preserves whichever timestamp was set
            # first — a later "attended" call must not overwrite an earlier
            # real booked_at with its own occurred_at.
            cur.execute(
                """
                INSERT INTO outcomes (campaign_id, patient_id, booked, attended, booked_at, attended_at)
                VALUES (%s,%s,TRUE,%s,%s,%s)
                ON CONFLICT (campaign_id) DO UPDATE SET
                  booked=TRUE,
                  attended=outcomes.attended OR EXCLUDED.attended,
                  booked_at=COALESCE(outcomes.booked_at, EXCLUDED.booked_at),
                  attended_at=COALESCE(outcomes.attended_at, EXCLUDED.attended_at),
                  recorded_at=now()
                """,
                (
                    attributed_campaign, data["patient_id"], status == "attended",
                    occurred_at, occurred_at if status == "attended" else None,
                ),
            )
    logger.info("%s stored booking=%s campaign=%s", event_type, data["booking_id"], campaign_id)


def find_booking(cur, data: dict, occurred_at: datetime):
    if data.get("booking_id"):
        cur.execute(
            """
            SELECT booking_id, campaign_id
            FROM bookings
            WHERE booking_id=%s AND patient_id=%s AND clinic_id=%s
              AND created_at <= %s
              AND created_at >= %s - (%s * interval '1 day')
            """,
            (
                data["booking_id"], data["patient_id"], data["clinic_id"],
                occurred_at, occurred_at, ATTRIBUTION_WINDOW_DAYS,
            ),
        )
    else:
        cur.execute(
            """
            SELECT booking_id, campaign_id
            FROM bookings
            WHERE patient_id=%s AND clinic_id=%s
              AND created_at <= %s
              AND created_at >= %s - (%s * interval '1 day')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (
                data["patient_id"], data["clinic_id"], occurred_at,
                occurred_at, ATTRIBUTION_WINDOW_DAYS,
            ),
        )
    return cur.fetchone()


def refresh_campaign_revenue(cur, campaign_id: str, patient_id: str) -> None:
    cur.execute(
        """
        INSERT INTO outcomes (campaign_id, patient_id, revenue)
        SELECT %s, %s, COALESCE(SUM(amount) FILTER (WHERE paid), 0)
        FROM revenue_attributions
        WHERE campaign_id=%s
        ON CONFLICT (campaign_id) DO UPDATE SET
          revenue=EXCLUDED.revenue,
          recorded_at=now()
        """,
        (campaign_id, patient_id, campaign_id),
    )


def record_revenue(event_type: str, event_id: str, data: dict, occurred_at: datetime) -> None:
    require(data, "patient_id", "clinic_id", "amount", "currency")
    invoice_id = data.get("invoice_id") or data.get("procedure_id")
    if not invoice_id:
        raise ValueError("Revenue event requires invoice_id or procedure_id")

    amount = Decimal(str(data["amount"]))
    paid = event_type == "Payment" or bool(data.get("paid", False))
    revenue_id = data.get("revenue_id") or str(uuid.uuid5(uuid.NAMESPACE_URL, f"velo:{invoice_id}"))

    with get_conn() as conn, conn.cursor() as cur:
        booking = find_booking(cur, data, occurred_at)
        booking_id, campaign_id = booking if booking else (None, None)
        cur.execute(
            """
            INSERT INTO revenue_attributions
              (revenue_id, invoice_id, procedure_id, booking_id, patient_id,
               clinic_id, campaign_id, amount, currency, paid, source_event_id, occurred_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (invoice_id) DO UPDATE SET
              procedure_id=COALESCE(EXCLUDED.procedure_id, revenue_attributions.procedure_id),
              booking_id=COALESCE(revenue_attributions.booking_id, EXCLUDED.booking_id),
              campaign_id=COALESCE(revenue_attributions.campaign_id, EXCLUDED.campaign_id),
              amount=EXCLUDED.amount,
              currency=EXCLUDED.currency,
              paid=revenue_attributions.paid OR EXCLUDED.paid,
              source_event_id=EXCLUDED.source_event_id,
              occurred_at=EXCLUDED.occurred_at,
              updated_at=now()
            RETURNING campaign_id
            """,
            (
                revenue_id, invoice_id, data.get("procedure_id"), booking_id,
                data["patient_id"], data["clinic_id"], campaign_id, amount,
                data["currency"].upper(), paid, event_id, occurred_at,
            ),
        )
        attributed_campaign = cur.fetchone()[0]
        if attributed_campaign:
            refresh_campaign_revenue(cur, attributed_campaign, data["patient_id"])
    logger.info("%s stored invoice=%s campaign=%s paid=%s", event_type, invoice_id, campaign_id, paid)


async def process_event(msg) -> None:
    try:
        payload = json.loads(msg.data.decode())
        event_type, event_id, data, occurred_at = event_parts(msg.subject, payload)
        if event_type in BOOKING_EVENTS:
            record_booking(event_type, event_id, data, occurred_at)
        elif event_type in REVENUE_EVENTS:
            record_revenue(event_type, event_id, data, occurred_at)
        else:
            logger.debug("Ignoring unsupported event type %s", event_type)
        await msg.ack()
    except Exception:
        logger.exception("Failed to process event on %s", msg.subject)
        await msg.nak(delay=5)


async def main() -> None:
    apply_migrations()
    nc = await nats.connect(os.getenv("NATS_URL", "nats://localhost:4222"))
    js = nc.jetstream()
    try:
        await js.add_stream(name="domain_events", subjects=["events.>"])
    except Exception:
        pass
    await js.subscribe(
        "events.>",
        durable="ve_measure_worker",
        config=ConsumerConfig(ack_policy=AckPolicy.EXPLICIT),
        cb=process_event,
    )
    logger.info("ve_measure started - listening on events.>")
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
