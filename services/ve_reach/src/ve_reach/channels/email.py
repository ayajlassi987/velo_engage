"""SendGrid email — not wired into any live dispatch path yet.

This completes the send mechanism itself (was a NotImplementedError stub —
see git history for channels/email_stub.py). What's still missing before
any campaign could actually use this channel, none of which was in scope
here since no family currently asks for it:
  1. A real recipient address — staging_patients has no email column at
     all (see infra/migrations/001_initial.sql), and ve_connect's Epic
     mapping never pulls Patient.telecom's email entry.
  2. A policy choice — no policies/opportunities/*.yml family lists
     `channel: email`.
  3. Dispatch wiring — subscriber.py's per-channel branching (WhatsApp
     primary, SMS fallback) has no email branch.

Uses SendGrid's v3 REST API directly over httpx (already a ve_reach
dependency) rather than adding the sendgrid SDK as a new dependency for a
single POST call.
"""

import httpx
import sys

sys.path.insert(0, ".")
from libs.ve_clients.vault_client import get_secret  # noqa: E402

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"


def send_email(to_address: str, subject: str, body: str) -> dict:
    api_key = get_secret("sendgrid", "api_key", "SENDGRID_API_KEY")
    from_address = get_secret("sendgrid", "from_address", "EMAIL_FROM_ADDRESS")
    if not (api_key and from_address):
        raise RuntimeError(
            "SendGrid is not configured — set SENDGRID_API_KEY and "
            "EMAIL_FROM_ADDRESS (directly or via Vault)."
        )
    payload = {
        "personalizations": [{"to": [{"email": to_address}]}],
        "from": {"email": from_address},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
    }
    with httpx.Client(timeout=10.0) as client:
        response = client.post(
            SENDGRID_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
    # SendGrid returns 202 with an empty body and the message id in a header
    # (no JSON to parse) — unlike Meta/Twilio's JSON-body responses.
    return {"status": "accepted", "message_id": response.headers.get("X-Message-Id")}
