"""Twilio SMS — fallback channel for when WhatsApp delivery fails.

Used when Meta reports a WhatsApp message as permanently failed (see
main.py's webhook handler) and the patient has separately granted SMS
consent for that opportunity's consent_class. Never used for the initial
send — WhatsApp stays primary per the master spec.
"""

import os
import sys

from twilio.rest import Client

sys.path.insert(0, ".")
from libs.ve_clients.vault_client import get_secret  # noqa: E402

# Read per-call rather than once at import time — this module gets imported
# during ve_reach's startup sequence, before there's any guarantee Vault has
# finished coming up; re-reading (cheap, lru_cached in vault_client) avoids
# permanently baking in a None from an early race.


def send_sms(to: str, body: str) -> dict:
    account_sid = get_secret("twilio", "account_sid", "TWILIO_ACCOUNT_SID")
    auth_token = get_secret("twilio", "auth_token", "TWILIO_AUTH_TOKEN")
    from_number = get_secret("twilio", "from_number", "TWILIO_FROM_NUMBER")
    if not (account_sid and auth_token and from_number):
        raise RuntimeError(
            "Twilio is not configured — set TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER (directly or via Vault)."
        )
    client = Client(account_sid, auth_token)
    message = client.messages.create(to=to, from_=from_number, body=body)
    return {"sid": message.sid, "status": message.status}
