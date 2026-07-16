# Velo Engage — Testing Guide

*Companion to `PROJECT_STATUS.md`. Run these in order from `~/velo-engage` unless noted. Each section is self-contained — skip to whatever you want to verify.*

---

## 0. Quick smoke test

```bash
docker compose -f infra/docker-compose.dev.yml ps
```
Every service should say `Up`/`healthy` (`ve_measure`, `ve_orchestrator`, `ve_temporal`, `ve_temporal_ui`, `ngrok` don't define healthchecks, so plain `Up` is fine).

```bash
curl -s http://localhost:8001/health   # ve_reach
curl -s http://localhost:8002/health   # ve_console
curl -s http://localhost:8003/health   # ve_connect
curl -s http://localhost:8090/api/stats  # ehr-emulator
curl -s https://YOUR-NGROK-DOMAIN/health  # public webhook tunnel, see infra/.env
```
All five should return JSON immediately. The `ngrok` service is supervised (`restart: unless-stopped`) — if it's ever down, `docker compose up -d` brings it back with no manual steps.

---

## 1. Full pipeline: all 15 families, guard logic, all 4 ML models

```bash
docker exec ve_temporal temporal schedule trigger \
  --address temporal:7233 --schedule-id daily-engagement-schedule
docker logs -f ve_orchestrator
```

Expect, in order:
- `evaluate_rules: N opportunities written across 15 active families`
- Some `<patient> blocked — X contacts in the last 30d, cap is 3` and/or `blocked — X.Xd since last contact, cooldown is 3d` lines (the guard logic — you should see at least a few of these on any run after the first)
- `gate_consent: X/Y passed (consent=..., not_over_messaged=..., after_dedup=...)`
- `ML scored N patients (no-show risk)`
- `ML scored N patients (booking propensity)`
- `ML scored N patients (expected revenue)`
- `ML scored N patients (uplift)`
- `rank_and_assign_holdout: N campaigns created`
- `dispatch_treated_to_reach: capping X treated campaigns to DISPATCH_LIMIT=1` then `published 1 campaigns to NATS`

If any of the four "ML scored" lines is missing and instead shows `... scoring failed (...) — using rule priority/neutral`, that model's Docker image is stale or MLflow is unreachable — rebuild the affected image (`docker compose -f infra/docker-compose.dev.yml up -d --build ve_orchestrator`) and retry.

### Confirm all 15 families are actually detected
```bash
docker exec ve_postgres psql -U velo -d velodb -c \
  "SELECT family, count(*) FROM opportunities GROUP BY family ORDER BY 1;"
```
All 15 letters (A,B,C,D,E,F,G,H,J,K,L,M,O,P,Q) should appear.

### Verify the expected-value formula end-to-end
```bash
docker exec ve_postgres psql -U velo -d velodb -c "
SELECT c.patient_id, c.family, o.priority_score, c.booking_propensity_score,
       c.value_score, c.uplift_score, c.expected_value_score, c.treatment_arm
FROM campaigns c JOIN opportunities o USING (opportunity_id)
WHERE c.uplift_score IS NOT NULL
ORDER BY c.created_at DESC LIMIT 10;
"
```
Check by hand: `expected_value_score ≈ priority_score × booking_propensity_score × value_score`, times `0.1` if `uplift_score <= 0`, times `1.0` otherwise. Rows should be sorted descending by `expected_value_score` when you look at `dispatch_treated_to_reach`'s selection (highest EV gets dispatched first once `DISPATCH_LIMIT` truncates).

---

## 2. The non-negotiable holdout safety gate

```bash
docker exec ve_postgres psql -U velo -d velodb -c \
  "SELECT * FROM campaigns WHERE treatment_arm='holdout' AND dispatched_at IS NOT NULL;"
```
Must return **0 new rows** (one pre-existing row from 2026-07-03, predating current safeguards, is expected and documented in `PROJECT_STATUS.md` — anything *else* here is a real problem).

Also worth re-confirming: a high expected-value patient can still land in holdout (proves random assignment is independent of ranking, which is required for the causal comparison to be valid):
```bash
docker exec ve_postgres psql -U velo -d velodb -c "
SELECT patient_id, expected_value_score, treatment_arm
FROM campaigns WHERE expected_value_score IS NOT NULL
ORDER BY expected_value_score DESC LIMIT 5;
"
```

---

## 3. Neo4j clinical-recall graph (family B)

```bash
docker exec ve_orchestrator python3 -c "
import sys; sys.path.insert(0, '/app/src')
from ve_orchestrator.graph_client import clinical_recall_due
import datetime
print(clinical_recall_due(['E11'], 55, 100, datetime.date.today()))
"
```
Should return a dict with `service: 'HbA1c monitoring'`, `specialty: 'Endocrinology'` (not Ophthalmology — that was the bug we fixed). Try `['J45']` (asthma → Pulmonology) and `['I10']` (hypertension → Cardiology) too.

```bash
docker exec ve_postgres psql -U velo -d velodb -c "
SELECT patient_id, rule_evidence->>'service' AS service, rule_evidence->>'specialty' AS specialty
FROM opportunities WHERE family='B' ORDER BY triggered_at DESC LIMIT 5;
"
```
Confirms live opportunities are using real per-patient graph evidence, not a flat boolean.

---

## 4. SHAP explainability (console)

```bash
CID=$(docker exec ve_postgres psql -U velo -d velodb -tAc \
  "SELECT campaign_id FROM campaigns WHERE booking_propensity_score IS NOT NULL ORDER BY created_at DESC LIMIT 1;")
echo "http://localhost:8002/campaigns/$CID"
```
Open that URL. Under "Campaign context" you should see a "Why this no-show score (XX%)" box listing the top contributing features with `+`/`-` SHAP values (red = increases risk, green = decreases it).

---

## 5. PSI drift monitoring

Open `http://localhost:8002/models`. Look for the "Prediction drift" card. It will likely say "Not enough data yet" — that's expected and correct right now (the synthetic dataset was bulk-seeded in a tight time window, so there's no real day-over-day spread to compare yet). It'll start reporting a real PSI value as more days of live-scheduled runs accumulate.

---

## 6. Redis online feature cache

```bash
docker exec ve_temporal temporal schedule trigger --address temporal:7233 --schedule-id daily-engagement-schedule
sleep 5
docker exec ve_redis redis-cli TTL "ve:patient_features:clinic_alnoor_001"   # should be a positive number <= 300
docker exec ve_temporal temporal schedule trigger --address temporal:7233 --schedule-id daily-engagement-schedule
sleep 5
docker logs ve_orchestrator 2>&1 | grep -i cache | tail -3   # should show "cache hit"
```

---

## 7. WhatsApp send + webhook status parsing

```bash
curl -s -X POST http://localhost:8001/send-test \
  -H "Content-Type: application/json" -d '{"family":"A","patient_name":"Test"}'
```
If the Meta token is current, expect `{"status":"sent",...}`. Then check the async delivery-status webhook came back:
```bash
docker exec ve_postgres psql -U velo -d velodb -c \
  "SELECT wa_message_id, status FROM outbound_messages ORDER BY sent_at DESC LIMIT 3;"
```

---

## 8. SMS fallback via Twilio

This fires automatically whenever Meta reports a dispatched campaign as `failed` — no need to force it manually. After running a few pipeline triggers (§1), check:
```bash
docker exec ve_postgres psql -U velo -d velodb -c "
SELECT wa_message_id, campaign_id, channel, template_name, source, status
FROM outbound_messages WHERE channel='sms' ORDER BY sent_at DESC LIMIT 5;
"
```
Any row here confirms a real automatic fallback fired. To check final delivery on the most recent one (no manual copy-paste needed):
```bash
SID=$(docker exec ve_postgres psql -U velo -d velodb -tAc \
  "SELECT wa_message_id FROM outbound_messages WHERE channel='sms' ORDER BY sent_at DESC LIMIT 1;")
docker exec ve_reach python3 -c "
import os
from twilio.rest import Client
client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
msg = client.messages('$SID').fetch()
print(msg.status, msg.error_code, msg.error_message)
"
```

---

## 9. Guard: cooldown, frequency cap, de-dup

Trigger the pipeline (§1) three or four times in a row and watch `ve_orchestrator` logs — you should see the *same* patients getting blocked with escalating reasons:
- First trigger: patient gets contacted normally.
- Next trigger within 3 days: `blocked — X.Xd since last contact, cooldown is 3d`.
- After several contacts in 30 days: `blocked — X contacts in the last 30d, cap is 3`.

For de-dup, find a patient matching multiple families on the same day and confirm only the highest-`priority_score` one produced a campaign:
```bash
docker exec ve_postgres psql -U velo -d velodb -c "
SELECT patient_id, family, priority_score FROM opportunities o
WHERE patient_id IN (
  SELECT patient_id FROM opportunities GROUP BY patient_id, triggered_at::date HAVING count(DISTINCT family) > 1
) ORDER BY patient_id, triggered_at DESC LIMIT 20;
"
```

---

## 10. Console — all 9 pages + live refresh

Open `http://localhost:8002` and click through: Overview, Opportunities, Campaigns, WhatsApp, Bookings, Revenue, Holdout, Models, Operations. Leave one open 15+ seconds and confirm the "Live" indicator ticks and content refreshes without a full page reload (Network tab should show a periodic fetch with header `X-VE-Live-Refresh: 1`).

---

## 11. Epic FHIR (VE Connect)

```bash
curl -s http://localhost:8003/health
curl -s http://localhost:8003/auth/config
```
`epic_configured` should be `true`. Full OAuth completion is pending Epic App Orchard support (see `PROJECT_STATUS.md` §3.6) — `/auth/login` will redirect correctly to Epic's real sandbox login, but the full flow doesn't complete yet.

---

## 12. Regression checks — the three original crash bugs

```bash
docker compose -f infra/docker-compose.dev.yml ps ve_reach ehr-emulator   # both "healthy", not restarting
docker exec ve_temporal temporal schedule describe --address temporal:7233 \
  --schedule-id daily-engagement-schedule | grep RunningWorkflows
# should print "RunningWorkflows   []" — not a stuck execution
```

---

If every section above checks out, the full pipeline — detection, ranking (all 4 ML models), guardrails, the holdout gate, both communication channels, and the console — is confirmed working end-to-end.
