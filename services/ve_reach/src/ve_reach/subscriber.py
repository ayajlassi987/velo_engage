import asyncio
import json
import logging
import os

import httpx
import nats
from nats.js.api import ConsumerConfig, AckPolicy

from ve_reach.sender import (
    build_campaign_message,
    build_campaign_text,
    send_template,
    send_text,
)
from ve_reach.db import (
    get_patient_phone, get_patient_name, get_sms_fallback_context, has_sms_consent,
    is_campaign_dispatched, mark_dispatched,
    save_message_id, save_outbound_message, upsert_outcome,
)

try:
    from ve_reach.channels.sms import send_sms
except ModuleNotFoundError:
    logging.getLogger(__name__).warning("twilio not installed — SMS fallback disabled.")
    send_sms = None

logger = logging.getLogger(__name__)
SANDBOX_OVERRIDE_NUMBER = os.getenv("RECIPIENT_TEST_NUMBER")


async def _attempt_sms_fallback(campaign_id: str) -> None:
    """WhatsApp just permanently failed for this campaign — fall back to SMS
    if Twilio is configured and the patient has separately granted SMS
    consent for this opportunity's consent_class. Shared by both the
    synchronous send-time failure path here (e.g. an expired access token
    rejected outright) and main.py's async delivery-status webhook path
    (e.g. Meta's post-send 131049 throttle) — moved here rather than kept
    in main.py so subscriber.py can call it without a circular import
    (main.py already imports start_subscriber from this module)."""
    if send_sms is None:
        return
    context = await asyncio.to_thread(get_sms_fallback_context, campaign_id)
    if not context or not context["phone_e164"]:
        return
    if not await asyncio.to_thread(
        has_sms_consent, context["patient_id"], context["clinic_id"], context["consent_class"]
    ):
        logger.info(f"SMS fallback skipped for {campaign_id[:8]}… — no SMS consent")
        return

    to = (
        os.getenv("SMS_FALLBACK_TEST_NUMBER")
        or os.getenv("RECIPIENT_TEST_NUMBER")
        or context["phone_e164"]
    )
    text_body = build_campaign_text(
        {"family": context["family"], "rule_evidence": context["rule_evidence"]},
        context["patient_name"],
    )
    try:
        result = await asyncio.to_thread(send_sms, to, text_body)
    except Exception as exc:
        logger.error(f"SMS fallback failed for {campaign_id[:8]}…: {exc}")
        return

    await asyncio.to_thread(
        save_outbound_message,
        result["sid"],
        to,
        context["clinic_id"],
        f"sms_fallback_family_{context['family'].lower()}",
        "campaign_sms_fallback",
        campaign_id,
        context["patient_id"],
        "sms",
    )
    logger.info(f"SMS fallback sent for {campaign_id[:8]}… sid={result['sid']}")


async def process_campaign(msg):
    try:
        campaign = json.loads(msg.data.decode())
        campaign_id = campaign["campaign_id"]
        patient_id = campaign["patient_id"]
        clinic_id = campaign["clinic_id"]
        family = campaign["family"]
        arm = campaign["treatment_arm"]

        if arm == "holdout":
            logger.warning(f"HOLDOUT campaign {campaign_id} reached ve_reach — dropping")
            await msg.ack()
            return

        if await asyncio.to_thread(is_campaign_dispatched, campaign_id):
            logger.info("Campaign %s already dispatched - acknowledging duplicate", campaign_id)
            await msg.ack()
            return

        logger.info(f"Processing campaign {campaign_id[:8]}… patient={patient_id} family={family}")

        real_phone = await asyncio.to_thread(get_patient_phone, patient_id, clinic_id)
        if not real_phone and not SANDBOX_OVERRIDE_NUMBER:
            logger.error(f"No phone found for {patient_id} — skipping")
            await msg.ack()
            return

        patient_name = await asyncio.to_thread(get_patient_name, patient_id, clinic_id)
        send_to = SANDBOX_OVERRIDE_NUMBER or real_phone
        if send_to != real_phone:
            logger.info(f"[SANDBOX] Redirecting from {real_phone or '(no phone on file)'} → {send_to}")

        message = build_campaign_message(campaign, patient_name)
        stored_template_name = message.name
        try:
            result = await asyncio.to_thread(
                send_template,
                send_to,
                message.name,
                message.language_code,
                message.components,
            )
        except httpx.HTTPStatusError as exc:
            try:
                meta_code = exc.response.json().get("error", {}).get("code")
            except (ValueError, AttributeError):
                meta_code = None
            if SANDBOX_OVERRIDE_NUMBER and meta_code == 132001:
                stored_template_name = f"session_text_family_{family.lower()}"
                logger.warning(
                    "Template %s is not approved; using session text for sandbox dispatch",
                    message.name,
                )
                result = await asyncio.to_thread(
                    send_text,
                    send_to,
                    build_campaign_text(campaign, patient_name),
                )
            else:
                raise
        wa_message_id = result.get("messages", [{}])[0].get("id")
        if wa_message_id:
            await asyncio.to_thread(
                save_message_id, wa_message_id, campaign_id, patient_id
            )
            await asyncio.to_thread(
                save_outbound_message,
                wa_message_id,
                send_to,
                clinic_id,
                stored_template_name,
                "campaign",
                campaign_id,
                patient_id,
            )
            logger.info(f"wa_message_id={wa_message_id} saved for campaign {campaign_id[:8]}…")

        await asyncio.to_thread(mark_dispatched, campaign_id)
        await asyncio.to_thread(upsert_outcome, campaign_id, patient_id)
        await msg.ack()
        logger.info(f"✅ Dispatched {campaign_id[:8]}… to {send_to}")

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if 400 <= status_code < 500 and status_code != 429:
            logger.error(
                "Permanent WhatsApp API error for campaign message: HTTP %s; "
                "terminating this delivery until a later workflow republishes it",
                status_code,
            )
            try:
                await _attempt_sms_fallback(campaign_id)
            except Exception:
                logger.error("SMS fallback attempt itself failed for %s", campaign_id[:8], exc_info=True)
            await msg.term()
        else:
            logger.error("Retryable WhatsApp API error: %s", exc, exc_info=True)
            await msg.nak(delay=30)
    except Exception as exc:
        logger.error("Error processing campaign: %s", exc, exc_info=True)
        await msg.nak(delay=30)


async def start_subscriber():
    """Connects to NATS and subscribes to campaigns.> — retries indefinitely
    on any failure (NATS/JetStream not ready yet is a real race against
    ve_orchestrator on a cold stack start, not a permanent condition) so a
    transient startup-ordering issue can never permanently silence this
    subscriber."""
    delay = 2
    while True:
        try:
            nc = await nats.connect(os.getenv("NATS_URL", "nats://localhost:4222"))
            js = nc.jetstream()
            # Idempotent — ve_orchestrator's dispatch activity also creates
            # this stream, but the subscriber must not depend on dispatch
            # having run first.
            try:
                await js.add_stream(name="campaigns", subjects=["campaigns.>"])
            except Exception:
                pass  # already exists
            try:
                await js.subscribe(
                    "campaigns.>", durable="ve_reach_worker",
                    config=ConsumerConfig(ack_policy=AckPolicy.EXPLICIT),
                    cb=process_campaign,
                )
            except Exception:
                await js.subscribe("campaigns.>", cb=process_campaign)
            break
        except Exception as exc:
            logger.error(f"start_subscriber: setup failed ({exc}) — retrying in {delay}s")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    logger.info("ve_reach subscriber started — listening on campaigns.>")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await nc.close()
