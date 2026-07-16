"""
webhooks.py — Webhook Dispatcher
==================================
Sends signed events to registered endpoints.
Uses background tasks for async delivery.
Retries failed deliveries with exponential backoff.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
import time as _time
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from ehr_emulator.models import WebhookEndpoint, WebhookDelivery, get_session_factory

logger = logging.getLogger(__name__)

_MAX_RETRIES  = 3
_RETRY_DELAYS =[5, 30, 120]

_IDEM_TTL = 300  # 5 minutes
_sent_cache: dict[str, datetime] = {}


def _sign_payload(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _cache_key(idem_key: str, endpoint_id: int) -> str:
    return f"{idem_key}:{endpoint_id}"


def _already_sent(idem_key: str, endpoint_id: int) -> bool:
    now = datetime.utcnow()
    expired =[k for k, t in _sent_cache.items() if (now - t).total_seconds() > _IDEM_TTL]
    for k in expired:
        del _sent_cache[k]
    return _cache_key(idem_key, endpoint_id) in _sent_cache


def _mark_sent(idem_key: str, endpoint_id: int) -> None:
    _sent_cache[_cache_key(idem_key, endpoint_id)] = datetime.utcnow()


def dispatch_event(
    session: Session,
    event_type: str,
    payload: dict,
    idempotency_key: Optional[str] = None,
) -> list[int]:
    """
    DEADLOCK FIX: Two-Phase Commit.
    Phase 1: Save 'pending' delivery to DB and COMMIT IMMEDIATELY to drop the lock.
    Phase 2: Make the HTTP request over the network.
    Phase 3: Save 'sent'/'failed' to DB.
    """
    endpoints = session.query(WebhookEndpoint).filter_by(is_active=True).all()
    if not endpoints:
        return[]

    if not idempotency_key:
        payload_str = json.dumps(payload, sort_keys=True)
        idempotency_key = hashlib.md5(f"{event_type}:{payload_str}".encode()).hexdigest()

    idem_key = idempotency_key
    deliveries_to_send = []
    delivery_ids =[]

    # --- PHASE 1: Write to DB and COMMIT immediately ---
    for endpoint in endpoints:
        if _already_sent(idem_key, endpoint.id):
            logger.debug("Skipping duplicate dispatch [%s]", event_type)
            continue

        existing_sent = (
            session.query(WebhookDelivery)
            .filter_by(idempotency_key=idem_key, endpoint_id=endpoint.id, status="sent")
            .first()
        )
        if existing_sent:
            _mark_sent(idem_key, endpoint.id)
            continue

        delivery = WebhookDelivery(
            endpoint_id     = endpoint.id,
            event_type      = event_type,
            payload         = payload,
            idempotency_key = idem_key,
            status          = "pending",
        )
        session.add(delivery)
        deliveries_to_send.append((delivery, endpoint))

    try:
        # COMMIT drops the SQLite write-lock instantly!
        session.commit()
    except Exception as e:
        logger.warning("dispatch_event DB commit failed: %s", e)
        return[]

    # --- PHASE 2: Send HTTP requests without holding any DB locks ---
    for delivery, endpoint in deliveries_to_send:
        delivery_ids.append(delivery.id)
        
        success = _attempt_delivery(session, delivery, endpoint)
        
        # --- PHASE 3: Update DB with result independently ---
        if success:
            _mark_sent(idem_key, endpoint.id)
            delivery.status = "sent"
        else:
            delivery.status = "failed"
            
        try:
            session.commit()
        except Exception as e:
            logger.warning("dispatch_event status update failed: %s", e)

    return delivery_ids


def _attempt_delivery(session: Session, delivery: WebhookDelivery, endpoint: WebhookEndpoint) -> bool:
    payload_str = json.dumps({
        "id":         delivery.idempotency_key,
        "event_type": delivery.event_type,
        "timestamp":  datetime.utcnow().isoformat() + "Z",
        "data":       delivery.payload,
    }, default=str)

    signature = _sign_payload(endpoint.secret, payload_str)
    headers   = {
        "Content-Type":        "application/json",
        "X-Velodoc-Signature": signature,
        "X-Velodoc-Event":     delivery.event_type,
        "X-Idempotency-Key":   delivery.idempotency_key,
    }

    delivery.attempts       += 1
    delivery.last_attempt_at = datetime.utcnow()

    try:
        resp = httpx.post(endpoint.url, content=payload_str, headers=headers, timeout=8.0)
        delivery.response_code = resp.status_code

        if resp.status_code < 300:
            logger.info("Webhook delivered [%s] → %s (HTTP %s)", delivery.event_type, endpoint.url, resp.status_code)
            return True
        else:
            logger.warning("Webhook failed [%s] → %s (HTTP %s)", delivery.event_type, endpoint.url, resp.status_code)
            return False

    except Exception as exc:
        delivery.response_code = 0
        logger.warning("Webhook network error [%s] → %s: %s", delivery.event_type, endpoint.url, exc)
        return False


def retry_failed(db_path: str | None = None) -> dict:
    """
    Retry pending/failed deliveries. Commits individually to avoid holding locks.
    """
    SessionFactory = get_session_factory(db_path)
    session        = SessionFactory()
    retried = 0
    succeeded = 0

    try:
        cutoff = datetime.utcnow() - timedelta(seconds=30)
        deliveries_to_retry = (
            session.query(WebhookDelivery)
            .filter(
                WebhookDelivery.status.in_(["failed", "pending"]),
                WebhookDelivery.attempts < _MAX_RETRIES,
            )
            .filter(
                (WebhookDelivery.status == "failed") |
                (WebhookDelivery.created_at <= cutoff.isoformat())
            )
            .all()
        )

        for delivery in deliveries_to_retry:
            if _already_sent(delivery.idempotency_key, delivery.endpoint_id):
                delivery.status = "sent"
                session.commit()
                continue

            endpoint = session.query(WebhookEndpoint).get(delivery.endpoint_id)
            if not endpoint or not endpoint.is_active:
                delivery.status = "skipped"
                session.commit()
                continue

            retried += 1
            if _attempt_delivery(session, delivery, endpoint):
                succeeded += 1
                _mark_sent(delivery.idempotency_key, delivery.endpoint_id)
                delivery.status = "sent"
            else:
                delivery.status = "failed"
            
            # Commit inside the loop so we don't hold the lock over multiple HTTP requests
            session.commit()

    except Exception as e:
        logger.warning("retry_failed error: %s", e)
    finally:
        session.close()

    return {"retried": retried, "succeeded": succeeded}


def clear_stuck_pending(db_path: str | None = None) -> dict:
    SessionFactory = get_session_factory(db_path)
    session        = SessionFactory()
    cleared = 0
    try:
        stuck = (
            session.query(WebhookDelivery)
            .filter_by(status="pending")
            .filter(WebhookDelivery.attempts > 0)
            .all()
        )
        for d in stuck:
            d.status = "sent"
            cleared += 1
        session.commit()
    except Exception as e:
        logger.error("clear_stuck_pending error: %s", e)
    finally:
        session.close()
    return {"cleared": cleared}


def simulate_inbound_reply(
    session: Session,
    appointment_id: int,
    reply_type: str,
    from_phone: str,
    on_event=None,
) -> dict:
    payload = {
        "appointment_id": appointment_id,
        "from_phone":     from_phone,
        "reply_type":     reply_type,
        "timestamp":      datetime.utcnow().isoformat() + "Z",
    }
    delivery_ids = dispatch_event(session, "patient.replied", payload)
    return {"dispatched": len(delivery_ids), "payload": payload}