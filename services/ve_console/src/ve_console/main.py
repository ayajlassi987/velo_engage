import os
import socket
import sys
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from ve_console.auth import PUBLIC_PATHS, current_user, require_admin, require_owner, router as auth_router

# ml/registry is copied in alongside src/ (see Dockerfile) so the console can
# explain a patient's no-show score with the same trained CatBoost model
# ve_orchestrator scores with — never crash the page if it's unavailable.
for _candidate in (Path(__file__).resolve().parents[4], Path("/app")):
    if _candidate and (_candidate / "ml").is_dir():
        sys.path.insert(0, str(_candidate))
        break
try:
    from ml.registry.scorer import explain_patient
except Exception:
    explain_patient = None

from libs.ve_clients.vault_client import get_secret

from ve_console.drift import compute_psi
from ve_console.model_quality import compute_classification_metrics

DRIFT_WINDOW_DAYS = int(os.getenv("DRIFT_WINDOW_DAYS", "3"))

PACKAGE_DIR = Path(__file__).parent
CLINIC_ID = os.getenv("CLINIC_ID", "clinic_alnoor_001")
CLINIC_NAME = os.getenv("CLINIC_NAME", "Al Noor Clinic")
MESSAGE_COST = Decimal(os.getenv("MESSAGE_COST", "0.05"))

app = FastAPI(title="VE Console", docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")

app.include_router(auth_router)


@app.middleware("http")
async def require_login(request: Request, call_next):
    if request.url.path in PUBLIC_PATHS or request.url.path.startswith("/static/"):
        return await call_next(request)
    if not request.session.get("user"):
        return RedirectResponse(f"/login?next={request.url.path}")
    return await call_next(request)


@app.middleware("http")
async def disable_dynamic_response_caching(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/") or response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


# Added last, so it's the outermost middleware layer (Starlette wraps
# add_middleware calls such that the last one added wraps everything added
# before it) — must run before require_login so request.session exists by
# the time that middleware reads it.
app.add_middleware(
    SessionMiddleware,
    secret_key=get_secret("keycloak", "session_secret", "SESSION_SECRET") or "dev-only-insecure-secret",
    same_site="lax",
)


@contextmanager
def db():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "velodb"),
        user=get_secret("postgres", "user", "DB_USER") or "velo",
        password=get_secret("postgres", "password", "DB_PASSWORD") or "velo_secret",
        cursor_factory=RealDictCursor,
    )
    try:
        yield conn
    finally:
        conn.close()


def query(sql: str, params=()):
    with db() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def one(sql: str, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def scalar(sql: str, params=(), default=0):
    row = one(sql, params)
    return next(iter(row.values())) if row else default


def format_datetime(value) -> str:
    if not value:
        return "-"
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value.astimezone(timezone.utc).strftime("%d %b %Y, %H:%M")


def format_money(value, currency="USD") -> str:
    return f"{currency or 'USD'} {Decimal(value or 0):,.2f}"


def format_percent(value) -> str:
    return f"{float(value or 0):.1f}%"


templates.env.filters["datetime"] = format_datetime
templates.env.filters["money"] = format_money
templates.env.filters["percent"] = format_percent


def render(request: Request, template: str, *, active: str, title: str, subtitle: str, **context):
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "active": active,
            "title": title,
            "subtitle": subtitle,
            "clinic_name": CLINIC_NAME,
            "clinic_id": CLINIC_ID,
            "now": datetime.now(timezone.utc),
            "user": request.session.get("user"),
            **context,
        },
    )


def clamp_limit(limit: int) -> int:
    return max(20, min(limit, 200))


# "Real" here means two separate things, both excluded:
#   1. scripts/seed_synthetic_phase1.py's directly-fabricated "syn_opp_.../
#      syn_campaign_..."-prefixed rows (fake outcomes, never touched the
#      real pipeline at all).
#   2. Genuine, real-pipeline-generated rows (today's deterministic SHA256
#      IDs or older hyphenated UUIDs — same real ID formats as truly real
#      Epic-patient rows) that nonetheless belong to a synthetic/seed
#      patient_id (SYN*, P0xx). Confirmed live this was a real, large gap:
#      before ve_orchestrator/feature_store.py was scoped to exclude
#      synthetic patients from evaluate_rules(), the daily pipeline had
#      been evaluating all ~20,000 synthetic patients every run for weeks,
#      writing ~382,000 real-format opportunity/campaign rows for them —
#      none "syn_"-prefixed, so #1 alone would have silently kept counting
#      them as real. Real Epic patient_ids are Epic FHIR IDs and never
#      match either prefix, so a patient_id check is the correct,
#      format-agnostic way to identify "real" here — same prefix logic as
#      feature_store.py's exclusion, kept consistent across both services.
# The doubled %% is not a typo — psycopg2's cursor.execute() does %-style
# substitution against the params tuple, so a literal % in the query text
# (as opposed to a %s placeholder) must be escaped as %% or it misparses
# the query and throws "IndexError: tuple index out of range".
_REAL_OPPORTUNITY = r"opportunity_id NOT LIKE 'syn_opp_%%' AND patient_id NOT LIKE 'SYN%%' AND patient_id NOT LIKE 'P0%%'"
_REAL_CAMPAIGN = r"campaign_id NOT LIKE 'syn_campaign_%%' AND patient_id NOT LIKE 'SYN%%' AND patient_id NOT LIKE 'P0%%'"


def _real_opportunity(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return (
        f"{prefix}opportunity_id NOT LIKE 'syn_opp_%%' AND "
        f"{prefix}patient_id NOT LIKE 'SYN%%' AND {prefix}patient_id NOT LIKE 'P0%%'"
    )


def _real_campaign(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return (
        f"{prefix}campaign_id NOT LIKE 'syn_campaign_%%' AND "
        f"{prefix}patient_id NOT LIKE 'SYN%%' AND {prefix}patient_id NOT LIKE 'P0%%'"
    )


def _real_or_unattributed_campaign(alias: str = "") -> str:
    """For tables like bookings/revenue_attributions where campaign_id can
    legitimately be NULL (a real, standalone booking with no campaign
    attribution) — excludes rows attributed to a *synthetic* campaign, and
    separately excludes rows belonging to a synthetic patient_id even when
    campaign_id is NULL (that OR branch would otherwise bypass the
    patient_id check entirely for unattributed rows)."""
    prefix = f"{alias}." if alias else ""
    return (
        f"({prefix}campaign_id IS NULL OR {_real_campaign(alias)}) AND "
        f"{prefix}patient_id NOT LIKE 'SYN%%' AND {prefix}patient_id NOT LIKE 'P0%%'"
    )


def overview_metrics():
    return one(
        f"""
        SELECT
          (SELECT COUNT(*) FROM opportunities WHERE clinic_id=%s AND {_REAL_OPPORTUNITY}) opportunities,
          (SELECT COUNT(*) FROM campaigns WHERE clinic_id=%s AND {_REAL_CAMPAIGN}) campaigns,
          (SELECT COUNT(*) FROM campaigns WHERE clinic_id=%s AND {_REAL_CAMPAIGN} AND dispatched_at IS NOT NULL) dispatched,
          (SELECT COUNT(*) FROM bookings WHERE clinic_id=%s AND {_real_or_unattributed_campaign()}) bookings,
          (SELECT COUNT(*) FROM bookings WHERE clinic_id=%s AND {_real_or_unattributed_campaign()} AND status='attended') attended,
          (SELECT COUNT(*) FROM inbound_messages i
             JOIN campaigns c ON c.campaign_id=i.campaign_id
             WHERE c.clinic_id=%s AND {_real_campaign("c")} AND i.detected_intent='booking_intent') booking_requests,
          (SELECT COALESCE(SUM(amount),0) FROM revenue_attributions
             WHERE clinic_id=%s AND paid AND campaign_id IS NOT NULL AND {_REAL_CAMPAIGN}) revenue
        """,
        (CLINIC_ID,) * 7,
    )


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/overview")


@app.get("/overview")
def overview(request: Request):
    metrics = overview_metrics()
    spend = Decimal(metrics["dispatched"] or 0) * MESSAGE_COST
    metrics["spend"] = spend
    metrics["roi"] = ((metrics["revenue"] - spend) / spend * 100) if spend else Decimal("0")
    metrics["booking_rate"] = (
        Decimal(metrics["bookings"]) / Decimal(metrics["campaigns"]) * 100
        if metrics["campaigns"] else Decimal("0")
    )

    funnel = one(
        f"""
        SELECT
          COUNT(*) FILTER (WHERE c.treatment_arm='treated') treated,
          COUNT(*) FILTER (WHERE c.dispatched_at IS NOT NULL) sent,
          COUNT(*) FILTER (WHERE COALESCE(o.delivered,FALSE)) delivered,
          COUNT(*) FILTER (WHERE COALESCE(o.read,FALSE)) read,
          COUNT(*) FILTER (WHERE COALESCE(o.replied,FALSE)) replied,
          COUNT(*) FILTER (WHERE EXISTS (
            SELECT 1 FROM inbound_messages i
            WHERE i.campaign_id=c.campaign_id
              AND i.detected_intent='booking_intent'
          )) booking_requested,
          COUNT(*) FILTER (WHERE COALESCE(o.booked,FALSE)) booked,
          COUNT(*) FILTER (WHERE COALESCE(o.attended,FALSE)) attended
        FROM campaigns c LEFT JOIN outcomes o USING (campaign_id)
        WHERE c.clinic_id=%s AND {_real_campaign("c")}
        """,
        (CLINIC_ID,),
    )
    funnel_max = max(funnel.values()) if funnel else 1

    recent_campaigns = query(
        f"""
        SELECT c.campaign_id, c.patient_id, c.family, c.treatment_arm, c.created_at,
               CASE WHEN COALESCE(o.attended,FALSE) THEN 'attended'
                    WHEN COALESCE(o.booked,FALSE) THEN 'booked'
                    WHEN COALESCE(o.replied,FALSE) THEN 'replied'
                    WHEN COALESCE(o.read,FALSE) THEN 'read'
                    WHEN COALESCE(o.delivered,FALSE) THEN 'delivered'
                    WHEN c.dispatched_at IS NOT NULL THEN 'sent' ELSE 'open' END status
        FROM campaigns c LEFT JOIN outcomes o USING (campaign_id)
        WHERE c.clinic_id=%s AND {_real_campaign("c")}
        ORDER BY c.created_at DESC LIMIT 8
        """,
        (CLINIC_ID,),
    )
    recent_inbound = query(
        """
        SELECT inbound_id, from_number, body, detected_intent, campaign_id, received_at
        FROM inbound_messages
        WHERE patient_id NOT LIKE 'SYN%%' AND patient_id NOT LIKE 'P0%%'
        ORDER BY received_at DESC LIMIT 5
        """
    )
    return render(
        request, "overview.html", active="overview", title="Clinic performance",
        subtitle="From identified opportunity to recovered revenue.", metrics=metrics,
        funnel=funnel, funnel_max=funnel_max, recent_campaigns=recent_campaigns,
        recent_inbound=recent_inbound,
    )


@app.get("/opportunities")
def opportunities(
    request: Request,
    q: str = "",
    family: str = "all",
    status: str = "all",
    limit: int = Query(100, ge=20, le=200),
):
    conditions = ["o.clinic_id=%s", _real_opportunity("o")]
    params = [CLINIC_ID]
    if q:
        conditions.append("(o.patient_id ILIKE %s OR o.rule_name ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if family != "all":
        conditions.append("o.family=%s")
        params.append(family)
    status_sql = """CASE
                    WHEN COALESCE(oc.attended,FALSE) THEN 'attended'
                    WHEN COALESCE(oc.booked,FALSE) THEN 'booked'
                    WHEN EXISTS (
                      SELECT 1 FROM inbound_messages i
                      WHERE i.campaign_id=c.campaign_id
                        AND i.detected_intent='booking_intent'
                    ) THEN 'booking_requested'
                    WHEN COALESCE(oc.replied,FALSE) THEN 'replied'
                    WHEN COALESCE(oc.read,FALSE) THEN 'read'
                    WHEN COALESCE(oc.delivered,FALSE) THEN 'delivered'
                    WHEN c.dispatched_at IS NOT NULL THEN 'sent'
                    WHEN c.treatment_arm='holdout' THEN 'holdout'
                    WHEN c.campaign_id IS NOT NULL THEN 'created'
                    ELSE 'open' END"""
    if status != "all":
        conditions.append(f"({status_sql})=%s")
        params.append(status)
    params.append(clamp_limit(limit))
    rows = query(
        f"""
        SELECT o.opportunity_id, o.patient_id, o.family, o.rule_name,
               o.priority_score, o.triggered_at, c.campaign_id,
               {status_sql} status
        FROM opportunities o
        LEFT JOIN campaigns c ON c.opportunity_id=o.opportunity_id
        LEFT JOIN outcomes oc ON oc.campaign_id=c.campaign_id
        WHERE {' AND '.join(conditions)}
        ORDER BY o.triggered_at DESC, o.priority_score DESC LIMIT %s
        """,
        tuple(params),
    )
    summary = one(
        f"""
        SELECT COUNT(*) total,
          COUNT(*) FILTER (WHERE c.campaign_id IS NULL) open,
          COUNT(*) FILTER (WHERE c.dispatched_at IS NOT NULL) sent,
          COUNT(*) FILTER (WHERE COALESCE(oc.booked,FALSE)) booked
        FROM opportunities o
        LEFT JOIN campaigns c ON c.opportunity_id=o.opportunity_id
        LEFT JOIN outcomes oc USING (campaign_id)
        WHERE o.clinic_id=%s AND {_real_opportunity("o")}
        """,
        (CLINIC_ID,),
    )
    families = [
        row["family"]
        for row in query(
            f"SELECT DISTINCT family FROM opportunities WHERE clinic_id=%s AND {_real_opportunity()} ORDER BY family",
            (CLINIC_ID,),
        )
    ]
    return render(
        request, "list.html", active="opportunities", title="Opportunities",
        subtitle="Patients currently eligible for clinic engagement.", rows=rows,
        summary=summary, filters={"q": q, "family": family, "status": status},
        families=families,
        filter_kind="opportunities",
        columns=[
            ("patient_id", "Patient", "text"), ("family", "Family", "family"),
            ("rule_name", "Reason", "text"), ("priority_score", "Priority", "score"),
            ("triggered_at", "Identified", "datetime"), ("status", "Status", "badge"),
            ("campaign_id", "Journey", "campaign"),
        ],
    )


@app.get("/campaigns")
def campaigns(
    request: Request,
    q: str = "",
    arm: str = "all",
    status: str = "all",
    limit: int = Query(100, ge=20, le=200),
):
    conditions = ["c.clinic_id=%s", _real_campaign("c")]
    params = [CLINIC_ID]
    if q:
        conditions.append("(c.patient_id ILIKE %s OR c.campaign_id ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if arm != "all":
        conditions.append("c.treatment_arm=%s")
        params.append(arm)
    status_sql = """CASE
                    WHEN COALESCE(o.attended,FALSE) THEN 'attended'
                    WHEN COALESCE(o.booked,FALSE) THEN 'booked'
                    WHEN EXISTS (
                      SELECT 1 FROM inbound_messages i
                      WHERE i.campaign_id=c.campaign_id
                        AND i.detected_intent='booking_intent'
                    ) THEN 'booking_requested'
                    WHEN COALESCE(o.replied,FALSE) THEN 'replied'
                    WHEN COALESCE(o.read,FALSE) THEN 'read'
                    WHEN COALESCE(o.delivered,FALSE) THEN 'delivered'
                    WHEN c.dispatched_at IS NOT NULL THEN 'sent'
                    WHEN c.treatment_arm='holdout' THEN 'holdout'
                    ELSE 'open' END"""
    if status != "all":
        conditions.append(f"({status_sql})=%s")
        params.append(status)
    params.append(clamp_limit(limit))
    rows = query(
        f"""
        SELECT c.campaign_id, c.patient_id, c.family, c.treatment_arm, c.created_at,
               c.dispatched_at, COALESCE(o.delivered,FALSE) delivered,
               COALESCE(o.read,FALSE) read, COALESCE(o.replied,FALSE) replied,
               COALESCE(o.booked,FALSE) booked, COALESCE(o.attended,FALSE) attended,
               COALESCE(o.revenue,0) revenue, {status_sql} status
        FROM campaigns c LEFT JOIN outcomes o USING (campaign_id)
        WHERE {' AND '.join(conditions)}
        ORDER BY c.created_at DESC, c.campaign_id LIMIT %s
        """,
        tuple(params),
    )
    summary = one(
        f"""
        SELECT COUNT(*) total,
          COUNT(*) FILTER (WHERE c.treatment_arm='treated') treated,
          COUNT(*) FILTER (WHERE c.treatment_arm='holdout') holdout,
          COUNT(*) FILTER (WHERE c.dispatched_at IS NOT NULL) sent,
          COUNT(*) FILTER (WHERE COALESCE(o.delivered,FALSE)) delivered,
          COUNT(*) FILTER (WHERE COALESCE(o.read,FALSE)) read,
          COUNT(*) FILTER (WHERE COALESCE(o.replied,FALSE)) replied,
          COUNT(*) FILTER (WHERE COALESCE(o.booked,FALSE)) booked
        FROM campaigns c LEFT JOIN outcomes o USING (campaign_id)
        WHERE c.clinic_id=%s AND {_real_campaign("c")}
        """,
        (CLINIC_ID,),
    )
    return render(
        request, "list.html", active="campaigns", title="Campaigns",
        subtitle="Treatment allocation and campaign execution status.", rows=rows,
        summary=summary, filters={"q": q, "arm": arm, "status": status},
        filter_kind="campaigns",
        columns=[
            ("campaign_id", "Campaign", "campaign"), ("patient_id", "Patient", "text"),
            ("family", "Family", "family"), ("treatment_arm", "Arm", "badge"),
            ("created_at", "Created", "datetime"), ("status", "Status", "badge"),
            ("dispatched_at", "Sent", "datetime"), ("revenue", "Revenue", "money"),
        ],
    )


@app.get("/campaigns/{campaign_id}")
def campaign_detail(request: Request, campaign_id: str):
    campaign = one(
        """
        SELECT c.*, o.priority_score, o.rule_name, o.rule_evidence,
               COALESCE(oc.delivered,FALSE) delivered, COALESCE(oc.read,FALSE) read,
               COALESCE(oc.replied,FALSE) replied, COALESCE(oc.booked,FALSE) booked,
               COALESCE(oc.attended,FALSE) attended, COALESCE(oc.revenue,0) revenue,
               EXISTS (
                 SELECT 1 FROM inbound_messages i
                 WHERE i.campaign_id=c.campaign_id
                   AND i.detected_intent='booking_intent'
               ) booking_requested
        FROM campaigns c
        LEFT JOIN opportunities o USING (opportunity_id)
        LEFT JOIN outcomes oc USING (campaign_id)
        WHERE c.campaign_id=%s
        """,
        (campaign_id,),
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    messages = query(
        "SELECT wa_message_id,created_at FROM wa_message_map WHERE campaign_id=%s ORDER BY created_at",
        (campaign_id,),
    )
    inbound = query(
        """SELECT inbound_id,from_number,message_type,body,detected_intent,received_at
           FROM inbound_messages WHERE campaign_id=%s ORDER BY received_at""",
        (campaign_id,),
    )
    bookings = query(
        """SELECT booking_id,appointment_date,status,created_at
           FROM bookings WHERE campaign_id=%s ORDER BY appointment_date""",
        (campaign_id,),
    )
    revenues = query(
        """SELECT invoice_id,booking_id,amount,currency,paid,occurred_at
           FROM revenue_attributions WHERE campaign_id=%s ORDER BY occurred_at""",
        (campaign_id,),
    )
    explanation = None
    if explain_patient is not None:
        features = one(
            "SELECT * FROM patient_features WHERE patient_id=%s AND clinic_id=%s",
            (campaign["patient_id"], campaign["clinic_id"]),
        )
        if features:
            try:
                explanation = explain_patient(dict(features))
            except Exception:
                explanation = None
    return render(
        request, "campaign_detail.html", active="campaigns", title="Campaign journey",
        subtitle=f"Patient {campaign['patient_id']} · {campaign_id}", campaign=campaign,
        messages=messages, inbound=inbound, bookings=bookings, revenues=revenues,
        explanation=explanation,
    )


@app.get("/whatsapp")
def whatsapp(request: Request, q: str = "", tab: str = "outbound"):
    search = f"%{q}%"
    outbound = query(
        f"""
        WITH message_ledger AS (
          SELECT om.wa_message_id,om.campaign_id,om.patient_id,c.family,om.recipient_e164,
                 om.source,om.status,om.sent_at AS dispatched_at,1 message_count,
                 (om.status IN ('delivered','read') OR COALESCE(o.delivered,FALSE)) delivered,
                 (om.status='read' OR COALESCE(o.read,FALSE)) read,
                 (om.replied OR COALESCE(o.replied,FALSE)) replied
          FROM outbound_messages om
          LEFT JOIN campaigns c ON c.campaign_id=om.campaign_id
          LEFT JOIN outcomes o ON o.campaign_id=om.campaign_id
          WHERE om.clinic_id=%s AND om.patient_id NOT LIKE 'SYN%%' AND om.patient_id NOT LIKE 'P0%%'

          UNION ALL

          SELECT NULL wa_message_id,c.campaign_id,c.patient_id,c.family,NULL recipient_e164,
                 'campaign' source,
                 CASE WHEN COALESCE(o.read,FALSE) THEN 'read'
                      WHEN COALESCE(o.delivered,FALSE) THEN 'delivered'
                      ELSE 'accepted' END status,
                 c.dispatched_at,COUNT(w.wa_message_id) message_count,
                 COALESCE(o.delivered,FALSE),COALESCE(o.read,FALSE),
                 COALESCE(o.replied,FALSE)
          FROM campaigns c
          LEFT JOIN outcomes o USING (campaign_id)
          LEFT JOIN wa_message_map w USING (campaign_id)
          WHERE c.clinic_id=%s AND c.treatment_arm='treated' AND {_real_campaign("c")}
            AND NOT EXISTS (
              SELECT 1 FROM outbound_messages om WHERE om.campaign_id=c.campaign_id
            )
          GROUP BY c.campaign_id,c.patient_id,c.family,c.dispatched_at,
                   o.delivered,o.read,o.replied
        )
        SELECT * FROM message_ledger
        WHERE (%s='' OR patient_id ILIKE %s OR campaign_id ILIKE %s
               OR recipient_e164 ILIKE %s)
        ORDER BY dispatched_at DESC NULLS LAST LIMIT 100
        """,
        (CLINIC_ID, CLINIC_ID, q, search, search, search),
    )
    inbound = query(
        """
        SELECT inbound_id,from_number,patient_id,campaign_id,message_type,body,
               detected_intent,received_at
        FROM inbound_messages
        WHERE (%s='' OR from_number ILIKE %s OR body ILIKE %s OR patient_id ILIKE %s)
          AND patient_id NOT LIKE 'SYN%%' AND patient_id NOT LIKE 'P0%%'
        ORDER BY received_at DESC LIMIT 100
        """,
        (q, search, search, search),
    )
    summary = one(
        f"""
        WITH campaign_metrics AS (
          SELECT COUNT(*) FILTER (WHERE c.dispatched_at IS NOT NULL) sent,
            COUNT(*) FILTER (WHERE COALESCE(o.delivered,FALSE)) delivered,
            COUNT(*) FILTER (WHERE COALESCE(o.read,FALSE)) read,
            COUNT(*) FILTER (WHERE COALESCE(o.replied,FALSE)) replied
          FROM campaigns c LEFT JOIN outcomes o USING (campaign_id)
          WHERE c.clinic_id=%s AND c.treatment_arm='treated' AND {_real_campaign("c")}
        ), manual_metrics AS (
          SELECT COUNT(*) sent,
            COUNT(*) FILTER (WHERE status IN ('delivered','read')) delivered,
            COUNT(*) FILTER (WHERE status='read') read,
            COUNT(*) FILTER (WHERE replied) replied
          FROM outbound_messages
          WHERE clinic_id=%s AND source='manual_test'
            AND patient_id NOT LIKE 'SYN%%' AND patient_id NOT LIKE 'P0%%'
        )
        SELECT c.sent+m.sent sent,c.delivered+m.delivered delivered,
               c.read+m.read read,c.replied+m.replied replied
        FROM campaign_metrics c CROSS JOIN manual_metrics m
        """,
        (CLINIC_ID, CLINIC_ID),
    )
    return render(
        request, "whatsapp.html", active="whatsapp", title="WhatsApp",
        subtitle="Outbound delivery and inbound patient conversations.", outbound=outbound,
        inbound=inbound, summary=summary, q=q, tab=tab,
    )


@app.get("/whatsapp/messages/{wa_message_id}", name="message_detail")
def message_detail(request: Request, wa_message_id: str):
    message = one(
        """
        SELECT om.*, c.family, c.treatment_arm,
               COALESCE(o.delivered,FALSE) campaign_delivered,
               COALESCE(o.read,FALSE) campaign_read,
               COALESCE(o.replied,FALSE) campaign_replied
        FROM outbound_messages om
        LEFT JOIN campaigns c ON c.campaign_id=om.campaign_id
        LEFT JOIN outcomes o ON o.campaign_id=om.campaign_id
        WHERE om.wa_message_id=%s AND om.clinic_id=%s
        """,
        (wa_message_id, CLINIC_ID),
    )
    if not message:
        raise HTTPException(status_code=404, detail="WhatsApp message not found")

    inbound = query(
        """
        SELECT i.inbound_id,i.from_number,i.message_type,i.body,
               i.detected_intent,i.received_at
        FROM inbound_messages i
        WHERE regexp_replace(i.from_number, '\\D', '', 'g') =
              regexp_replace(%s, '\\D', '', 'g')
          AND i.received_at >= %s
          AND i.received_at <= %s + INTERVAL '30 days'
          AND NOT EXISTS (
            SELECT 1 FROM outbound_messages newer
            WHERE newer.clinic_id=%s
              AND regexp_replace(newer.recipient_e164, '\\D', '', 'g') =
                  regexp_replace(i.from_number, '\\D', '', 'g')
              AND newer.sent_at > %s
              AND newer.sent_at <= i.received_at
          )
        ORDER BY i.received_at
        """,
        (
            message["recipient_e164"], message["sent_at"], message["sent_at"],
            CLINIC_ID, message["sent_at"],
        ),
    )
    delivered = message["status"] in ("delivered", "read") or message["campaign_delivered"]
    read = message["status"] == "read" or message["campaign_read"]
    replied = message["replied"] or message["campaign_replied"]
    return render(
        request, "message_detail.html", active="whatsapp", title="WhatsApp message",
        subtitle=f"Recipient {message['recipient_e164']}", message=message,
        inbound=inbound, delivered=delivered, read=read, replied=replied,
    )


@app.get("/clinical-summaries")
def clinical_summaries(request: Request, q: str = "", limit: int = 100):
    """Task 2 (MedGemma + NemoGuard clinical note intelligence). Only
    structured extraction output is ever stored (see
    infra/migrations/014_clinical_extractions.sql) — no raw clinical note
    text exists anywhere in this database, per the retention decision in
    PROJECT_STATUS.md. validation_flags are always shown, never hidden,
    same "honest gap" pattern as /models' insufficient_data states —
    the presence of flags means a human should double-check that row, not
    that anything failed silently."""
    conditions = ["clinic_id=%s"]
    params = [CLINIC_ID]
    if q:
        conditions.append("patient_id ILIKE %s")
        params.append(f"%{q}%")
    params.append(clamp_limit(limit))
    rows = query(
        f"""
        SELECT extraction_id, patient_id, document_reference_id, note_date,
               diagnoses, medications, procedures, follow_up_recommendations,
               clinical_risks, safety_check_passed, validation_flags, extracted_at
        FROM clinical_extractions
        WHERE {' AND '.join(conditions)}
        ORDER BY extracted_at DESC LIMIT %s
        """,
        tuple(params),
    )
    summary = one(
        """
        SELECT COUNT(*) total,
          COUNT(*) FILTER (WHERE validation_flags IS NOT NULL AND jsonb_array_length(validation_flags) > 0) flagged,
          COUNT(DISTINCT patient_id) patients
        FROM clinical_extractions WHERE clinic_id=%s
        """,
        (CLINIC_ID,),
    )
    return render(
        request, "list.html", active="clinical-summaries", title="Clinical summaries",
        subtitle="Structured extractions from clinical notes (MedGemma + NemoGuard) — no raw note text is ever stored.",
        rows=rows, summary=summary, filters={"q": q}, filter_kind="clinical-summaries",
        columns=[
            ("patient_id", "Patient", "text"), ("diagnoses", "Diagnoses", "list"),
            ("medications", "Medications", "list"), ("procedures", "Procedures", "list"),
            ("follow_up_recommendations", "Follow-up", "list"), ("clinical_risks", "Risks", "list"),
            ("validation_flags", "Quality", "flags"), ("extracted_at", "Extracted", "datetime"),
        ],
    )


@app.get("/bookings")
def bookings(request: Request, q: str = "", status: str = "all", limit: int = 100):
    conditions = ["b.clinic_id=%s", _real_or_unattributed_campaign("b")]
    params = [CLINIC_ID]
    if q:
        conditions.append("(b.patient_id ILIKE %s OR b.booking_id ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if status != "all":
        conditions.append("b.status=%s")
        params.append(status)
    params.append(clamp_limit(limit))
    rows = query(
        f"""
        SELECT b.booking_id,b.patient_id,b.campaign_id,b.appointment_date,b.status,
               b.created_at,COALESCE(SUM(r.amount) FILTER (WHERE r.paid),0) revenue
        FROM bookings b LEFT JOIN revenue_attributions r USING (booking_id)
        WHERE {' AND '.join(conditions)}
        GROUP BY b.booking_id ORDER BY b.appointment_date DESC LIMIT %s
        """,
        tuple(params),
    )
    summary = one(
        f"""
        SELECT COUNT(*) total,
          COUNT(*) FILTER (WHERE status='booked') booked,
          COUNT(*) FILTER (WHERE status='attended') attended,
          COUNT(*) FILTER (WHERE campaign_id IS NOT NULL) attributed
        FROM bookings WHERE clinic_id=%s AND {_real_or_unattributed_campaign()}
        """,
        (CLINIC_ID,),
    )
    return render(
        request, "list.html", active="bookings", title="Bookings",
        subtitle="Appointments attributed to engagement campaigns.", rows=rows,
        summary=summary, filters={"q": q, "status": status}, filter_kind="bookings",
        columns=[
            ("booking_id", "Booking", "mono"), ("patient_id", "Patient", "text"),
            ("appointment_date", "Appointment", "datetime"), ("status", "Status", "badge"),
            ("campaign_id", "Campaign", "campaign"), ("revenue", "Paid revenue", "money"),
        ],
    )


@app.get("/revenue")
def revenue(request: Request, q: str = "", state: str = "all", limit: int = 100, _owner=Depends(require_owner)):
    conditions = ["r.clinic_id=%s", _real_or_unattributed_campaign("r")]
    params = [CLINIC_ID]
    if q:
        conditions.append("(r.patient_id ILIKE %s OR r.invoice_id ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if state == "paid":
        conditions.append("r.paid")
    elif state == "unpaid":
        conditions.append("NOT r.paid")
    params.append(clamp_limit(limit))
    rows = query(
        f"""
        SELECT r.invoice_id,r.patient_id,r.booking_id,r.campaign_id,r.amount,
               r.currency,r.paid,r.occurred_at
        FROM revenue_attributions r WHERE {' AND '.join(conditions)}
        ORDER BY r.occurred_at DESC LIMIT %s
        """,
        tuple(params),
    )
    summary = one(
        f"""
        SELECT COUNT(*) invoices,COUNT(*) FILTER (WHERE paid) paid,
          COALESCE(SUM(amount) FILTER (WHERE paid AND campaign_id IS NOT NULL AND {_REAL_CAMPAIGN}),0) recovered,
          COALESCE(SUM(amount) FILTER (WHERE NOT paid),0) outstanding
        FROM revenue_attributions WHERE clinic_id=%s AND {_real_or_unattributed_campaign()}
        """,
        (CLINIC_ID,),
    )
    dispatched = scalar(
        f"SELECT COUNT(*) FROM campaigns WHERE clinic_id=%s AND dispatched_at IS NOT NULL AND {_REAL_CAMPAIGN}",
        (CLINIC_ID,),
    )
    spend = Decimal(dispatched) * MESSAGE_COST
    summary["spend"] = spend
    summary["roi"] = ((summary["recovered"] - spend) / spend * 100) if spend else 0
    return render(
        request, "list.html", active="revenue", title="Recovered revenue",
        subtitle="Paid billing linked back to campaign-attributed bookings.", rows=rows,
        summary=summary, filters={"q": q, "state": state}, filter_kind="revenue",
        columns=[
            ("invoice_id", "Invoice", "mono"), ("patient_id", "Patient", "text"),
            ("amount", "Amount", "money_with_currency"), ("paid", "Payment", "paid"),
            ("booking_id", "Booking", "mono"), ("campaign_id", "Campaign", "campaign"),
            ("occurred_at", "Occurred", "datetime"),
        ],
    )


@app.get("/holdout")
def holdout(request: Request, _owner=Depends(require_owner)):
    rows = query(
        f"""
        SELECT c.treatment_arm,COUNT(*) campaigns,
          COUNT(*) FILTER (WHERE c.dispatched_at IS NOT NULL) dispatched,
          COUNT(*) FILTER (WHERE COALESCE(o.booked,FALSE)) booked,
          COUNT(*) FILTER (WHERE COALESCE(o.attended,FALSE)) attended,
          COALESCE(SUM(o.revenue),0) revenue
        FROM campaigns c LEFT JOIN outcomes o USING (campaign_id)
        WHERE c.clinic_id=%s AND {_real_campaign("c")} GROUP BY c.treatment_arm ORDER BY c.treatment_arm DESC
        """,
        (CLINIC_ID,),
    )
    by_arm = {row["treatment_arm"]: row for row in rows}
    for row in rows:
        row["booking_rate"] = row["booked"] / row["campaigns"] * 100 if row["campaigns"] else 0
        row["attendance_rate"] = row["attended"] / row["booked"] * 100 if row["booked"] else 0
    treated = by_arm.get("treated", {"campaigns": 0, "booked": 0})
    control = by_arm.get("holdout", {"campaigns": 0, "booked": 0})
    treated_rate = treated["booked"] / treated["campaigns"] * 100 if treated["campaigns"] else 0
    holdout_rate = control["booked"] / control["campaigns"] * 100 if control["campaigns"] else 0
    stats = {
        "treated_rate": treated_rate, "holdout_rate": holdout_rate,
        "absolute_lift": treated_rate - holdout_rate,
        "relative_lift": ((treated_rate / holdout_rate) - 1) * 100 if holdout_rate else 0,
        "holdout_dispatches": scalar(
            f"SELECT COUNT(*) FROM campaigns WHERE clinic_id=%s AND treatment_arm='holdout' AND dispatched_at IS NOT NULL AND {_REAL_CAMPAIGN}",
            (CLINIC_ID,),
        ),
    }
    return render(
        request, "holdout.html", active="holdout", title="Holdout analysis",
        subtitle="Causal comparison of treated and naturally converting patients.",
        rows=rows, stats=stats,
    )


# One entry per registered MLflow model. score_column is the campaigns
# column its predictions land in (for drift, Phase 3a) — None where nothing
# is persisted as a continuous score (intent's prediction is a label, see
# below). uplift's two arms (treated/control) share one combined output
# column since campaigns.uplift_score is already p_treated - p_control, not
# a per-arm score.
REGISTERED_MODELS = [
    {"model_name": "ve_noshow_v1", "label": "No-show", "score_column": "noshow_score"},
    {"model_name": "velo_engage_booking_propensity", "label": "Booking propensity", "score_column": "booking_propensity_score"},
    {"model_name": "velo_engage_value_amount", "label": "Value (amount)", "score_column": "value_score"},
    {"model_name": "velo_engage_uplift_treated", "label": "Uplift (treated arm)", "score_column": "uplift_score"},
    {"model_name": "velo_engage_uplift_control", "label": "Uplift (control arm)", "score_column": "uplift_score"},
    {"model_name": "ve_intent_v1", "label": "Intent classifier", "score_column": None},
]


def _latest_run_metrics(run_id: str | None) -> dict:
    if not run_id:
        return {}
    rows = query(
        "SELECT DISTINCT ON (key) key, value FROM metrics WHERE run_uuid=%s ORDER BY key, timestamp DESC",
        (run_id,),
    )
    return {row["key"]: row["value"] for row in rows}


def _score_drift(score_column: str) -> dict | None:
    score_rows = query(
        f"SELECT {score_column} AS score, created_at FROM campaigns "
        f"WHERE clinic_id=%s AND {score_column} IS NOT NULL AND {_REAL_CAMPAIGN} ORDER BY created_at",
        (CLINIC_ID,),
    )
    if not score_rows:
        return None
    cutoff = score_rows[-1]["created_at"] - timedelta(days=DRIFT_WINDOW_DAYS)
    baseline = [float(r["score"]) for r in score_rows if r["created_at"] < cutoff]
    current = [float(r["score"]) for r in score_rows if r["created_at"] >= cutoff]
    drift = compute_psi(baseline, current)
    drift["window_days"] = DRIFT_WINDOW_DAYS
    return drift


# Population-level, not per-model: these three are the only numeric,
# directly-queryable patient_features columns shared across the
# propensity/uplift feature lists (the rest of those lists are categorical
# — family, sex, open_treatment_plan_flag — which this PSI implementation
# can't bucket meaningfully; noshow's features are booking-time properties
# that mostly don't exist in patient_features at all, filled from
# ml/registry/scorer.py's DEFAULTS instead). Catches upstream feature-
# pipeline drift (e.g. an Epic data shape change) independent of whether
# any model's own score output happens to look stable.
FEATURE_DRIFT_COLUMNS = ["age", "days_since_last_visit", "visit_cadence_baseline"]


def _feature_drift(column: str) -> dict | None:
    rows = query(
        f"SELECT {column} AS value, as_of_timestamp AS ts FROM patient_features "
        f"WHERE clinic_id=%s AND {column} IS NOT NULL "
        f"AND patient_id NOT LIKE 'SYN%%' AND patient_id NOT LIKE 'P0%%' ORDER BY ts",
        (CLINIC_ID,),
    )
    if not rows:
        return None
    cutoff = rows[-1]["ts"] - timedelta(days=DRIFT_WINDOW_DAYS)
    baseline = [float(r["value"]) for r in rows if r["ts"] < cutoff]
    current = [float(r["value"]) for r in rows if r["ts"] >= cutoff]
    drift = compute_psi(baseline, current)
    drift["window_days"] = DRIFT_WINDOW_DAYS
    return drift


# Only noshow and propensity have a direct, unambiguous ground-truth column
# to score against (see model_quality.py's own docstring for why value/
# uplift are deliberately excluded rather than force-fit).
_QUALITY_QUERIES = {
    "ve_noshow_v1": """
        SELECT c.noshow_score AS score, NOT o.attended AS label
        FROM campaigns c JOIN outcomes o USING (campaign_id)
        WHERE c.clinic_id=%s AND o.booked=true AND o.attended IS NOT NULL
          AND c.noshow_score IS NOT NULL AND {cohort}
    """,
    "velo_engage_booking_propensity": """
        SELECT c.booking_propensity_score AS score, o.booked AS label
        FROM campaigns c JOIN outcomes o USING (campaign_id)
        WHERE c.clinic_id=%s AND c.dispatched_at IS NOT NULL
          AND c.booking_propensity_score IS NOT NULL AND {cohort}
    """,
}
_SYNTHETIC_COHORT = "(c.patient_id LIKE 'SYN%%' OR c.patient_id LIKE 'P0%%')"
_REAL_COHORT = "(c.patient_id NOT LIKE 'SYN%%' AND c.patient_id NOT LIKE 'P0%%')"


def _model_quality(model_name: str, cohort_sql: str) -> dict | None:
    template = _QUALITY_QUERIES.get(model_name)
    if not template:
        return None
    rows = query(template.format(cohort=cohort_sql), (CLINIC_ID,))
    if not rows:
        return None
    scores = [float(r["score"]) for r in rows]
    labels = [bool(r["label"]) for r in rows]
    return compute_classification_metrics(scores, labels)


@app.get("/models")
def models(request: Request, _admin=Depends(require_admin)):
    versions = query(
        """
        SELECT mv.name,mv.version,mv.creation_time AS creation_timestamp,
               mv.current_stage,mv.status,
               mv.run_id,r.status run_status
        FROM model_versions mv LEFT JOIN runs r ON r.run_uuid=mv.run_id
        ORDER BY mv.creation_time DESC LIMIT 60
        """
    )
    versions_by_model: dict[str, list] = {}
    for row in versions:
        versions_by_model.setdefault(row["name"], []).append(row)

    # Drift is per score column, not per model name (uplift's two models
    # share one output column) — compute once, reuse across matching cards.
    drift_by_score = {
        entry["score_column"]: _score_drift(entry["score_column"])
        for entry in REGISTERED_MODELS
        if entry["score_column"]
    }

    model_cards = []
    for entry in REGISTERED_MODELS:
        model_versions = versions_by_model.get(entry["model_name"], [])
        # Prefer the version actually staged Production (what's live, per
        # ml/registry/_stage_loader.py) for the metrics card; fall back to
        # the most recently registered version if nothing's been promoted
        # yet — mirrors the scorer's own fallback so the dashboard shows
        # what's actually being served.
        production = [v for v in model_versions if v["current_stage"] == "Production"]
        headline_version = production[0] if production else (model_versions[0] if model_versions else None)
        model_cards.append({
            **entry,
            "versions": model_versions,
            "headline_version": headline_version,
            "metrics": _latest_run_metrics(headline_version["run_id"]) if headline_version else {},
            "drift": drift_by_score.get(entry["score_column"]) if entry["score_column"] else None,
            "quality_synthetic": _model_quality(entry["model_name"], _SYNTHETIC_COHORT),
            "quality_real": _model_quality(entry["model_name"], _REAL_COHORT),
        })

    feature_drift = {column: _feature_drift(column) for column in FEATURE_DRIFT_COLUMNS}

    return render(
        request, "models.html", active="models", title="ML models",
        subtitle="Training runs, registered versions, and drift across every model.",
        model_cards=model_cards, versions=versions, mlflow_url="http://localhost:5000",
        feature_drift=feature_drift, alerts=_model_alerts(),
    )


def _model_alerts() -> list[dict]:
    """Minimal alerting: no Slack/email/PagerDuty integration exists
    anywhere in this codebase, so this surfaces as a dashboard banner
    (same pattern /operations already uses for service health) rather than
    a notification channel built from scratch for this one feature."""
    alerts = []
    for entry in REGISTERED_MODELS:
        if not entry["score_column"]:
            continue
        drift = _score_drift(entry["score_column"])
        if drift and drift.get("status") == "critical":
            alerts.append({
                "label": f"{entry['label']} score drift",
                "detail": f"PSI {drift['psi']} over the last {drift['window_days']}d — significant shift from baseline.",
            })
    for column in FEATURE_DRIFT_COLUMNS:
        drift = _feature_drift(column)
        if drift and drift.get("status") == "critical":
            alerts.append({
                "label": f"Feature drift: {column}",
                "detail": f"PSI {drift['psi']} over the last {drift['window_days']}d — upstream feature pipeline may have shifted.",
            })
    return alerts


def http_health(url: str):
    try:
        with urllib.request.urlopen(url, timeout=1.2) as response:
            return response.status < 400
    except Exception:
        return False


def tcp_health(host: str, port: int):
    try:
        with socket.create_connection((host, port), timeout=1.2):
            return True
    except OSError:
        return False


@app.get("/operations")
def operations(request: Request, _admin=Depends(require_admin)):
    services = [
        {"name": "Postgres", "role": "Clinical and campaign data", "ok": tcp_health("postgres", 5432), "url": None},
        {"name": "NATS JetStream", "role": "Campaign and event messaging", "ok": http_health("http://nats:8222/healthz"), "url": "http://localhost:8222"},
        {"name": "Temporal", "role": "Daily workflow orchestration", "ok": tcp_health("temporal", 7233), "url": "http://localhost:8080"},
        {"name": "MLflow", "role": "Model tracking and registry", "ok": http_health("http://mlflow:5000/health"), "url": "http://localhost:5000"},
        {"name": "Neo4j", "role": "Relationship graph", "ok": http_health("http://neo4j:7474"), "url": "http://localhost:7474"},
        {"name": "Keycloak", "role": "Identity and access", "ok": http_health("http://keycloak:8080/realms/master"), "url": "http://localhost:8081"},
        {"name": "Vault", "role": "Secrets management", "ok": http_health("http://vault:8200/v1/sys/health"), "url": "http://localhost:8200"},
    ]
    return render(
        request, "operations.html", active="operations", title="System operations",
        subtitle="Live connectivity across the Velo Engage platform.", services=services,
        healthy=sum(service["ok"] for service in services), alerts=_model_alerts(),
    )


@app.get("/api/summary")
def api_summary():
    metrics = overview_metrics()
    return {key: float(value) if isinstance(value, Decimal) else value for key, value in metrics.items()}


@app.get("/health")
def health():
    scalar("SELECT 1")
    return {"status": "ok", "service": "ve_console"}


@app.exception_handler(HTTPException)
async def forbidden_page(request: Request, exc: HTTPException):
    if exc.status_code == 403 and "text/html" in request.headers.get("accept", ""):
        return render(
            request, "forbidden.html", active="", title="Access restricted",
            subtitle="This page is limited to the clinic owner.", detail=exc.detail,
        )
    return await http_exception_handler(request, exc)
