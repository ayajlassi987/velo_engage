# 7. Communication Channels

## Purpose

Once a campaign is dispatched (file 1/6), something has to actually deliver
it to the patient, handle delivery failures gracefully, and capture
whatever the patient does in response. All of this lives in `ve_reach`.

## WhatsApp — primary channel

`services/ve_reach/src/ve_reach/subscriber.py` consumes dispatched
campaigns from NATS JetStream (published by `dispatch_treated_to_reach`),
looks up the patient's phone number (`staging_patients.phone_e164`), builds
the approved WhatsApp template message for that family
(`sender.py`'s `build_campaign_message`), and calls Meta's Cloud API
(`send_template`).

- **Sandbox/test override**: `RECIPIENT_TEST_NUMBER` env var, read as
  `SANDBOX_OVERRIDE_NUMBER`, redirects every send to one real test number
  regardless of the patient's actual phone — necessary because Epic sandbox
  patients have fake/placeholder phone numbers. Originally this override
  only ever *substituted* for an existing phone value; patients with no
  phone at all still got skipped before the override logic ran. Fixed so a
  missing phone doesn't block a send when the override is configured (see
  `13_known_gaps_and_roadmap.md`).
- **Inbound webhook** (`main.py`'s `POST /webhook`): handles two kinds of
  Meta callbacks in one payload — **status updates** (delivered/read/failed,
  written to `outcomes.delivered`/`.read` via `upsert_outcome`, with a
  `failed` status triggering the SMS fallback) and **inbound messages**
  (patient replies). Reply handling uses a **deterministic keyword match**
  (e.g. "STOP" → `opt_out`) as the gating signal that actually revokes
  consent — because that has to work even if the ML intent model is
  unavailable — with the ML classifier's richer intent label logged
  alongside it as additional signal, not as the sole gate for something as
  consequential as opt-out.
- **`upsert_outcome`** (`ve_reach/db.py`): the idempotent write both the
  webhook handler and `ve_measure`'s booking listener share. Each per-stage
  timestamp (`delivered_at`, `read_at`, ...) is only ever set the *first*
  time that stage becomes true — a naive `= now()` on every call would
  clobber real timing data with whatever the latest call happened to be,
  which is exactly the bug that made duration/timing analysis impossible
  before this was fixed (the fix that made the survival model's training
  data meaningful — see file 4).

## SMS — automatic fallback, never primary

`services/ve_reach/src/ve_reach/channels/sms.py`, via Twilio. Fires
automatically (`_attempt_sms_fallback` in `subscriber.py`) whenever Meta
reports a WhatsApp send as permanently `failed` — **and** the patient has
separately granted SMS consent for that opportunity's specific
`consent_class` (the same per-class consent discipline as file 3, not a
blanket "they're on WhatsApp so SMS is fine too" assumption). Never used
for the initial send; WhatsApp stays primary per the master spec.

## Email — built, deliberately not wired into dispatch

`services/ve_reach/src/ve_reach/channels/email.py`. Uses SendGrid's v3 REST
API directly over `httpx` (no new SDK dependency for one POST call).
Completes the actual send mechanism — configured, tested against a mocked
HTTP boundary (payload shape, missing-config error, HTTP-error
propagation) — but **not connected to live dispatch**, because three
things it would need don't exist yet and weren't in scope to add
speculatively: `staging_patients` has no email column at all, no Epic
mapping ever pulls `Patient.telecom`'s email entry, and no
`policies/opportunities/*.yml` family lists `channel: email`. Building
those without a concrete need would be infrastructure for a channel
nothing currently uses.

## Why this shape

- **Channel isolation with a clear primary/fallback relationship**, not
  three independent equally-weighted channels — matches how the master
  spec actually describes reaching patients (WhatsApp-first, appropriate
  for the target market), and keeps the fallback logic (SMS-specific
  consent check, Meta-failure-triggered) in one obvious place rather than
  spread across every family's policy.
- **A dual gating signal for opt-out** (deterministic keyword + ML intent
  logged alongside) rather than trusting the ML classifier alone for
  something this consequential — a low-confidence misclassification should
  never be the only thing standing between a patient and continued
  unwanted contact.
- **Complete the mechanism, don't fabricate the wiring** for email — a
  real, working, tested send function is genuinely useful groundwork; a
  fake dispatch path routing to a channel with no recipient data would just
  be dead code pretending to be a feature.
