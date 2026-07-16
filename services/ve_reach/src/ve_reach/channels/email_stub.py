"""STUB — email fallback channel. NOT FUNCTIONAL.

The master spec lists email as a secondary channel behind WhatsApp/SMS. No
SMTP/transactional-email provider (SES, Sendgrid, Postmark, ...) is
configured in this environment, so this module only documents the intended
interface — it does not send anything.

To make this real:
  1. Pick a provider, add its SDK/credentials as env vars
     (e.g. SENDGRID_API_KEY or SMTP_HOST/SMTP_USER/SMTP_PASSWORD).
  2. Replace the body of send_email() with a real send call.
  3. Add an `email` template variant alongside the WhatsApp template in each
     policies/opportunities/*.yml family that should support it.
"""

STATUS = "stub"  # not wired into any live code path


def send_email(to_address: str, subject: str, body: str) -> dict:
    raise NotImplementedError(
        "Email channel is a stub. Configure a provider and implement "
        "ve_reach.channels.email_stub.send_email() before routing any campaign here."
    )
