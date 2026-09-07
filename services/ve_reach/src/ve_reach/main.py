import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
import httpx
load_dotenv()

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from ve_reach.subscriber import start_subscriber, _attempt_sms_fallback
from ve_reach.db import (
    lookup_campaign_by_wa_id,
    revoke_consent_by_phone,
    save_inbound_message,
    save_outbound_message,
    update_outbound_status,
    upsert_outcome,
)
from ve_reach.sender import (
    build_campaign_message,
    build_campaign_text,
    send_template,
    send_text,
)
from ve_reach.policy_catalog import PolicyError, active_families, policy_for_family

import sys
sys.path.insert(0, ".")
from libs.ve_clients.vault_client import get_secret
try:
    from ml.registry.intent_scorer import classify
except ModuleNotFoundError:
    import logging
    logging.getLogger(__name__).warning(
        "ml.registry.intent_scorer not found — intent scoring disabled."
    )
    classify = lambda text: {"intent": "UNKNOWN", "confidence": 0.0}
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)




def _log_subscriber_death(task: asyncio.Task) -> None:
    # start_subscriber() retries forever internally, so reaching here at all
    # means it crashed past its own retry loop — never let that be silent.
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("ve_reach subscriber task died unexpectedly", exc_info=exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(start_subscriber())
    task.add_done_callback(_log_subscriber_death)
    yield
    task.cancel()


app = FastAPI(title="ve_reach", lifespan=lifespan)

# Epic's registered redirect_uri for this app is one bare ngrok domain with
# no path (see ve_connect/auth.py's callback() docstring) — Epic requires an
# exact match, and ngrok's free tier only grants one reserved domain, so
# that single domain has to serve both WhatsApp webhooks (this service,
# natively) and Epic's OAuth login/callback (ve_connect's real handlers) at
# once. Before this, the two purposes required manually stopping this
# service's tunnel and standing up a temporary one pointed at ve_connect
# every time the Epic sandbox token needed re-authorizing, then swapping
# back — a real recurring chore, and a real risk of forgetting to swap back
# and silently losing WhatsApp delivery-status webhooks. These three routes
# forward to ve_connect's actual handlers instead, so the one tunnel serves
# both permanently.
VE_CONNECT_URL = os.getenv("VE_CONNECT_URL", "http://ve_connect:8000")


@app.get("/auth/login")
async def proxy_epic_login():
    async with httpx.AsyncClient(follow_redirects=False, timeout=15.0) as client:
        resp = await client.get(f"{VE_CONNECT_URL}/auth/login")
    # ve_connect's handler returns a redirect straight to Epic's own
    # authorize URL (computed entirely from Epic settings, not ve_connect's
    # own address) — relaying just the Location header and status is
    # sufficient, no need to touch the rest of the response.
    return RedirectResponse(resp.headers["location"], status_code=resp.status_code)


async def _proxy_epic_callback(code: str, state: str) -> JSONResponse:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{VE_CONNECT_URL}/auth/callback", params={"code": code, "state": state}
        )
    return JSONResponse(content=resp.json(), status_code=resp.status_code)


@app.get("/auth/callback")
async def proxy_epic_callback(code: str, state: str):
    return await _proxy_epic_callback(code, state)


@app.get("/")
async def proxy_epic_root(code: str, state: str):
    # Mirrors ve_connect's own dual /auth/callback + "/" registration — see
    # that docstring for why Epic's redirect can land on the bare root path.
    return await _proxy_epic_callback(code, state)


def _message_text(message: dict) -> str | None:
    message_type = message.get("type")
    if message_type == "text":
        return message.get("text", {}).get("body", "").strip() or None
    if message_type == "button":
        button = message.get("button", {})
        return (button.get("text") or button.get("payload") or "").strip() or None
    if message_type == "interactive":
        interactive = message.get("interactive", {})
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return (reply.get("title") or reply.get("id") or "").strip() or None
    return None


def _message_intent(text: str | None) -> str:
    normalized = (text or "").strip().upper()
    if normalized in {"STOP", "UNSUBSCRIBE", "CANCEL", "إلغاء"}:
        return "opt_out"
    if normalized in {"BOOK", "BOOKED", "YES", "نعم", "حجز"}:
        return "booking_intent"
    return "unknown"


# _attempt_sms_fallback now lives in subscriber.py (shared by both this
# module's async delivery-status webhook path and subscriber.py's own
# synchronous send-time failure path — see subscriber.py for why it moved).


@app.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    expected_token = get_secret("whatsapp", "webhook_verify_token", "WEBHOOK_VERIFY_TOKEN") or "velo_webhook_secret_2024"
    if hub_mode == "subscribe" and hub_verify_token == expected_token:
        logger.info("Webhook verified successfully")
        return hub_challenge
    raise HTTPException(status_code=403, detail="Verification failed")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ve_reach"}


# Public signing key for ve_connect's Epic Bulk Data Backend Services app —
# hosted here (not on ve_connect) because this service already sits behind
# the stable reserved ngrok domain; Epic fetches this URL to verify the
# client-assertion JWTs ve_connect signs for bulk $export token requests.
# Public key only — never the private half.
EPIC_BULK_JWKS = {
    "keys": [
        {
            "kty": "RSA",
            "kid": "cd3666b5-29dd-4fa4-9ffa-795e408c14e9",
            "use": "sig",
            "alg": "RS384",
            "n": "8V_jvb-rqvGo-Nnw2_wNadIu2x-lB5_ewtZFp3hbWzEsYWjBQvTa-tPyD_M5AxT7z66SzP8VXnCFAIF_udGSPEbfPAWtNuxTDIC9-3Otd55pqk9-lcxDsVK6Ub3w-yqjyLddCcqDCf7LtqDS3KUgX_X-hOwwseIwXT37MNsjo_qguIZbhTOHcKcNmHlpfRUv6iPF_AFWI8xJ6VKgUrsjYgp9YrF5g1gIe7-NGukG4LencBN18jJmfhnAl2QuYRQT7KemumEMwzv_dspHJAXn32Roj3-BqWw7-gh_4T_4Jd2NMVE8I1Mwn8QuMsOjJCwIf9K2M3UmhoiB9xG8z7fR6w",
            "e": "AQAB",
        }
    ]
}


@app.get("/.well-known/jwks.json")
async def epic_bulk_jwks():
    return EPIC_BULK_JWKS


@app.post("/webhook")
async def receive_webhook(request: Request):
    body = await request.json()
    logger.debug(f"Webhook payload: {json.dumps(body, indent=2)}")

    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            for status_update in value.get("statuses", []):
                wa_message_id = status_update.get("id")
                status = status_update.get("status")
                if not wa_message_id or not status:
                    continue
                await asyncio.to_thread(update_outbound_status, wa_message_id, status)
                lookup = await asyncio.to_thread(lookup_campaign_by_wa_id, wa_message_id)
                if lookup:
                    campaign_id, patient_id = lookup
                    await asyncio.to_thread(
                        upsert_outcome,
                        campaign_id,
                        patient_id,
                        delivered=status in ("delivered", "read"),
                        read=status == "read",
                    )
                    if status == "failed":
                        await _attempt_sms_fallback(campaign_id)
                if status == "failed" and status_update.get("errors"):
                    for err in status_update["errors"]:
                        logger.warning(
                            "Status update: %s -> failed (code=%s title=%s message=%s)",
                            wa_message_id, err.get("code"), err.get("title"), err.get("message"),
                        )
                else:
                    logger.info(f"Status update: {wa_message_id} -> {status}")

            for message in value.get("messages", []):
                from_number = message.get("from")
                text_body = _message_text(message)
                # Deterministic keyword match drives gating behavior (opt-out,
                # booking-request counter) — it must work even if the MLflow
                # intent model is unavailable. The ML classification below is
                # logged alongside it as a richer, non-gating signal.
                intent = _message_intent(text_body)
                ml_result = classify(text_body)
                logger.info(
                    f"Inbound from {from_number}: intent={intent} "
                    f"ml_intent={ml_result['intent']} (conf={ml_result['confidence']}) "
                    f"body={text_body!r}"
                )

                received_at = None
                timestamp = message.get("timestamp")
                if timestamp:
                    received_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)

                await asyncio.to_thread(
                    save_inbound_message,
                    message.get("id"),
                    from_number,
                    message.get("type", "unknown"),
                    text_body,
                    intent,
                    received_at,
                )

                if intent == "opt_out" and from_number:
                    revoked = await asyncio.to_thread(revoke_consent_by_phone, from_number)
                    logger.info(f"Revoked WhatsApp consent for {from_number} ({revoked} row(s))")

    return {"status": "ok"}


@app.post("/send-test")
async def send_test(request: Request):
    body = await request.json()
    to = body.get("to") or os.getenv("RECIPIENT_TEST_NUMBER")
    if not to:
        raise HTTPException(
            status_code=400,
            detail="Provide 'to' or configure RECIPIENT_TEST_NUMBER",
        )

    family = str(body.get("family", "A")).upper()
    try:
        policy_for_family(family)
    except PolicyError as exc:
        raise HTTPException(
            status_code=400,
            detail={"message": str(exc), "active_families": active_families()},
        ) from exc
    patient_name = str(body.get("patient_name", "Aya"))
    campaign = {
        "family": family,
        "rule_evidence": {
            "days_until_expiry": int(body.get("days_until_expiry", 30)),
        },
    }
    message = build_campaign_message(campaign, patient_name)

    delivery_mode = "template"
    stored_template_name = message.name
    fallback_reason = None
    try:
        result = await asyncio.to_thread(
            send_template,
            to=to,
            template_name=message.name,
            language_code=message.language_code,
            components=message.components,
        )
    except httpx.HTTPStatusError as exc:
        try:
            meta_error = exc.response.json().get("error", {})
            meta_message = meta_error.get("message", "Meta rejected the request")
            meta_code = meta_error.get("code")
            meta_subcode = meta_error.get("error_subcode")
        except (ValueError, AttributeError):
            meta_message = exc.response.text or "Meta rejected the request"
            meta_code = None
            meta_subcode = None
        logger.error(
            "WhatsApp test failed: %s (code=%s, subcode=%s)",
            meta_message,
            meta_code,
            meta_subcode,
        )
        if meta_code == 132001:
            delivery_mode = "session_text"
            stored_template_name = f"session_text_family_{family.lower()}"
            fallback_reason = "Campaign template is awaiting Meta approval"
            try:
                result = await asyncio.to_thread(
                    send_text,
                    to,
                    build_campaign_text(campaign, patient_name),
                )
            except httpx.HTTPStatusError as fallback_exc:
                try:
                    fallback_error = fallback_exc.response.json().get("error", {})
                except (ValueError, AttributeError):
                    fallback_error = {}
                raise HTTPException(
                    status_code=502,
                    detail={
                        "message": fallback_error.get(
                            "message",
                            "The template is pending and the 24-hour reply window is closed",
                        ),
                        "meta_code": fallback_error.get("code"),
                        "template_name": message.name,
                        "template_status": "PENDING",
                    },
                ) from fallback_exc
        else:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": meta_message,
                    "meta_code": meta_code,
                    "meta_subcode": meta_subcode,
                    "template_name": message.name,
                },
            ) from exc
    wa_message_id = result.get("messages", [{}])[0].get("id")
    if wa_message_id:
        await asyncio.to_thread(
            save_outbound_message,
            wa_message_id,
            to,
            os.getenv("CLINIC_ID", "clinic_alnoor_001"),
            stored_template_name,
            "manual_test",
        )

    return {
        "status": "sent",
        "family": family,
        "template_name": message.name,
        "delivery_mode": delivery_mode,
        "fallback_reason": fallback_reason,
        "wa_message_id": wa_message_id,
        "result": result,
        }