# Velo Engage

Velo Engage turns patient signals into consent-checked opportunities, assigns
treated and holdout campaigns, sends treated campaigns through WhatsApp, and
attributes replies, bookings, attendance, and revenue back to campaigns.

## Daily End-to-End Runbook

Use this section each day. Do not run the seed or database reset scripts as
part of the normal daily startup.

### 1. Check the WhatsApp configuration

Confirm that `services/ve_reach/.env` contains a valid Meta access token and
the correct test number:

```dotenv
WHATSAPP_ACCESS_TOKEN=...
RECIPIENT_TEST_NUMBER=+216...
```

Every enabled family's `delivery.template.name` in
`policies/opportunities/*.yml` must be approved in WhatsApp Manager before
normal outbound campaigns can use it.

While templates are pending, development campaigns can use session text only
when the test recipient has messaged the business during the last 24 hours.

### 2. Start every Docker service

From the project root:

```bash
cd ~/velo-engage/infra
docker compose -f docker-compose.dev.yml up -d
```

After code or dependency changes, rebuild instead:

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

This starts PostgreSQL, NATS, Temporal, the Temporal worker, Reach, Measure,
the console, MLflow, and the supporting infrastructure. Reach is already
Dockerized, so do not start a second Uvicorn process on port `8001`.

### 3. Verify service health

```bash
docker compose -f docker-compose.dev.yml ps
curl http://localhost:8001/health
curl http://localhost:8002/health
docker logs --tail 20 ve_orchestrator
docker logs --tail 20 ve_reach
```

Expected worker messages:

```text
Worker started - listening on 'velo-engage-task-queue'
ve_reach subscriber started - listening on campaigns.>
```

The important containers should show `Up` or `healthy`, including:

```text
ve_postgres
ve_nats
ve_temporal
ve_orchestrator
ve_reach
ve_measure
ve_console
```

### 4. The Meta webhook tunnel

The ngrok tunnel is a supervised `docker-compose` service (`ngrok`, container
`ve_ngrok`) — it starts with `docker compose up -d` like everything else and
restarts automatically if it crashes. Nothing to run manually. Its
credentials live in `infra/.env` (`NGROK_AUTHTOKEN`, `NGROK_DOMAIN`) — see
`infra/.env.example` if that file doesn't exist yet.

Verify it's up:
```bash
curl -s https://YOUR-NGROK-DOMAIN/health
```

If you ever need to change the domain, update `NGROK_DOMAIN` in `infra/.env`
and update the callback in Meta Developer Dashboard to match:

```text
https://YOUR-NGROK-DOMAIN/webhook
```

The Meta webhook verify token must match `WEBHOOK_VERIFY_TOKEN` in
`services/ve_reach/.env`.

### 5. Check the daily Temporal schedule

```bash
docker exec ve_temporal temporal schedule list \
  --address temporal:7233
```

Multi-clinic productization (see `PROJECT_STATUS.md` §10) replaced the single
hand-created schedule with one per clinic, created via
`services/ve_orchestrator/src/ve_orchestrator/schedules.py`:
`daily-engagement-schedule-{clinic_id}` — e.g. `daily-engagement-schedule-clinic_alnoor_001`.
Each runs automatically every day at `02:00 UTC`, which is `03:00` in Lagos.
Starting Docker after that time does not require a manual run unless you
specifically want to execute the pipeline immediately.

### 6. Run the flow immediately when needed

To demonstrate or test the full flow without waiting for the next schedule
(swap in the clinic you want to trigger):

```bash
docker exec ve_temporal temporal schedule trigger \
  --address temporal:7233 \
  --schedule-id daily-engagement-schedule-clinic_alnoor_001
```

This runs:

```text
Rules -> Opportunities -> Consent -> Holdout assignment -> Campaign
      -> NATS -> VE Reach -> WhatsApp -> Webhook -> Outcomes -> Dashboard
```

#### What updates at each stage

| Event | Database/UI change |
| --- | --- |
| A rule matches a patient | Opportunities increases |
| Temporal assigns treated or holdout | Campaigns increases |
| Reach sends a treated campaign | Dispatched/Sent increases and an outbound message is stored |
| Meta reports `delivered` | Delivered increases |
| Meta reports `read` | Read increases |
| The patient replies | Replied increases |
| The patient replies `BOOK`, `BOOKED`, or `YES` | Booking requests increases |
| The clinic emits `AppointmentConfirmed` | Attributed bookings increases |
| The clinic emits `AppointmentCompleted` | Attended visits increases |
| The clinic emits a paid `Payment` event | Recovered revenue and ROI update |
| The patient replies `STOP` | WhatsApp consent is revoked for future campaigns |

A sent message must not directly increase appointments, attendance, or
revenue. Those counters represent real downstream clinic events. Manual
`/send-test` messages also do not create opportunities or campaigns because
they bypass the Temporal workflow.

The development configuration is intentionally limited to:

- `WORKFLOW_BATCH_LIMIT=25`: process 25 opportunities per workflow run
- `DISPATCH_LIMIT=1`: send at most one campaign per workflow run
- `RECIPIENT_TEST_NUMBER`: redirect the development send to the test phone

Keep these safeguards enabled while using synthetic data and a Meta test
number.

### 7. Watch the automated run

In two terminals:

```bash
docker logs -f ve_orchestrator
```

```bash
docker logs -f ve_reach
```

The orchestrator should report opportunities, consent, treated/holdout
assignment, and one NATS publication. Reach should report the selected
campaign, WhatsApp message ID, and later the delivered/read webhook updates.

Press `Ctrl+C` to stop following logs. This does not stop the containers.

### 8. Open the interfaces

- VE Console: http://localhost:8002
- WhatsApp activity: http://localhost:8002/whatsapp
- Campaigns: http://localhost:8002/campaigns
- Temporal UI: http://localhost:8080
- MLflow: http://localhost:5000
- NATS monitoring: http://localhost:8222
- Neo4j Browser: http://localhost:7474 (clinical-recall graph, `neo4j`/`velo_secret`)
- VE Connect (Epic FHIR): http://localhost:8003/health

The console refreshes automatically. Open a campaign to inspect its complete
message, reply, booking, attendance, and revenue journey.

### 9. Verify the database result

Latest automated campaign and WhatsApp state:

```bash
docker exec -it ve_postgres psql -U velo -d velodb -c "
SELECT c.campaign_id,
       c.patient_id,
       c.family,
       c.treatment_arm,
       c.dispatched_at,
       om.template_name,
       om.status,
       o.delivered,
       o.read,
       o.replied
FROM campaigns c
JOIN outbound_messages om USING (campaign_id)
LEFT JOIN outcomes o USING (campaign_id)
ORDER BY om.sent_at DESC
LIMIT 10;
"
```

Mandatory holdout safety check:

```bash
docker exec -it ve_postgres psql -U velo -d velodb -c "
SELECT *
FROM campaigns
WHERE treatment_arm='holdout'
  AND dispatched_at IS NOT NULL;
"
```

Expected: `0 rows`.

### 10. Stop everything at the end of the day

```bash
cd ~/velo-engage/infra
docker compose -f docker-compose.dev.yml down
```
This also stops the `ngrok` service — nothing to stop manually.

Docker volumes preserve PostgreSQL, MLflow, Neo4j, and other persistent data.
Do not add `-v` unless you intentionally want to delete those volumes.

## Optional Manual WhatsApp Test

This checks Meta connectivity independently of Temporal and NATS. It is not
required for the normal automated flow.

```bash
curl -X POST http://localhost:8001/send-test \
  -H "Content-Type: application/json" \
  -d '{"family":"A","patient_name":"Aya"}'
```

Families:

- `A`: dormant-patient recall
- `C`: open-treatment-plan follow-up
- `G`: expiring-benefits reminder; pass `"days_until_expiry":30`

## Initial Demo Data Only

Run this only when creating a new development database:

```bash
cd ~/velo-engage
uv run python scripts/seed_dummy_patients.py
```

For the larger ML and holdout dataset:

```bash
uv run python scripts/seed_synthetic_phase1.py
uv run python ml/feature_pipelines/build_training_dataset.py
uv run python ml/training/train_propensity.py
```

To seed the VE Graph clinical-recall knowledge graph in Neo4j (idempotent,
safe to re-run — family B queries this live):

```bash
uv run python scripts/seed_neo4j_clinical_graph.py
```

## Common Problems

### Port 8001 is already in use

Reach now runs in Docker. Stop any locally started Uvicorn process, then start
the Compose service again:

```bash
fuser -k 8001/tcp
cd ~/velo-engage/infra
docker compose -f docker-compose.dev.yml up -d ve_reach
```

### Meta authentication error 190

The temporary access token expired. Generate a new token in Meta Developer
Dashboard, update `WHATSAPP_ACCESS_TOKEN`, and recreate Reach:

```bash
cd ~/velo-engage/infra
docker compose -f docker-compose.dev.yml up -d --force-recreate ve_reach
```

### Meta template error 132001

The requested template/language is not approved for the WhatsApp Business
Account. Check its status in WhatsApp Manager. Development session text only
works during the 24-hour window after the test recipient sends a message.

### Webhook statuses do not update

Confirm the `ngrok` service is healthy, the Meta callback URL points to
`/webhook`, and Reach receives POST requests:

```bash
docker compose -f infra/docker-compose.dev.yml ps ngrok
curl -s https://YOUR-NGROK-DOMAIN/health
docker logs -f ve_reach
```

## Project Interfaces

The console connects these operational views:

- `/overview`: clinic funnel, bookings, attendance, revenue, and ROI
- `/opportunities`: rule-generated patient opportunities
- `/campaigns`: treated/holdout execution and campaign journeys
- `/whatsapp`: outbound delivery and inbound replies
- `/bookings`: attributed appointments and attendance
- `/revenue`: invoices, payments, recovered revenue, and ROI
- `/holdout`: treated-versus-control conversion analysis
- `/models`: MLflow propensity models and training runs
- `/operations`: infrastructure health and service links

See `services/ve_measure/README.md` for event contracts and
`RELEASE_CHECKLIST.md` for release validation.

## Module Status (what's real vs. stub)

The master architecture names more modules than any one deployment needs on
day one. This table is the honest map from that architecture to what's
actually running, so nobody mistakes a stub for a shipped feature.

| Spec module | Status | Where |
| --- | --- | --- |
| VE Connect (FHIR ingestion) | **Real, not auto-run.** Runs in Docker (`ve_connect`, port 8003) with real SMART-on-FHIR OAuth2/PKCE code. `/health` honestly reports `degraded` until real Epic sandbox credentials are set in `services/ve_connect/.env`. | `services/ve_connect` |
| VE Store (feature store) | **Real, pragmatic.** Postgres `patient_features` is the offline/authoritative store; Redis runs but is not yet used as an online cache. | `patient_features` table |
| VE Graph (clinical-recall graph) | **Real.** Neo4j seeded with `(:Condition)-[:REQUIRES_FOLLOWUP]->(:Service)`, age-band screening, and specialty `DELIVERED_BY`/`IMPLIES_REFERRAL` edges. Family B queries it live for per-patient evidence (falls back to the flat `clinical_recall_due_flag` if Neo4j is unreachable). | `scripts/seed_neo4j_clinical_graph.py`, `services/ve_orchestrator/src/ve_orchestrator/graph_client.py` |
| VE Rules (declarative engine) | **Real.** All 15 R/D families in `policies/opportunities/*.yml`, evaluated by a structured YAML operator engine (no `eval`). | `services/ve_orchestrator/src/ve_orchestrator/policy_engine.py` |
| VE Intel (detection + ML scoring) | **Real.** A trained, calibrated CatBoost no-show/propensity model (`ve_noshow_v1` in MLflow) scores every candidate before ranking. | `ml/registry/scorer.py`, called from `rank_and_assign_holdout` |
| VE Guard (consent/frequency/de-dup) | **Real.** Consent-class gating, a 3-day cooldown, a 3-contacts/30-day cap, and one-primary-opportunity-per-patient de-dup (clinical families outrank commercial by design priority). | `gate_consent` in `services/ve_orchestrator/src/ve_orchestrator/activities.py` |
| VE Decide (holdout + ranking) | **Real.** Randomized 15% holdout, deterministic per run-date, EV-style ranking by priority × ML score. | `rank_and_assign_holdout` |
| VE Agent (LangGraph orchestrator) | **Stub, not deployed.** Temporal (`ve_orchestrator`) is the real live orchestrator — durable retries/replay beat a hand-rolled loop. A LangGraph `StateGraph` with the same node shape exists and runs, but every node is a placeholder and it's not in `docker-compose.dev.yml` or the `uv` workspace. | `services/ve_agent` (see its README) |
| VE Reach — WhatsApp | **Real.** Templates, session-text fallback, inbound webhook parsing, opt-out, delivery/read tracking. | `services/ve_reach` |
| VE Reach — SMS (Twilio) | **Stub, not functional.** No Twilio account configured. | `services/ve_reach/src/ve_reach/channels/sms_stub.py` |
| VE Reach — Email | **Stub, not functional.** No email provider configured. | `services/ve_reach/src/ve_reach/channels/email_stub.py` |
| VE Reach — LLM personalization (MedGemma+NemoGuard) | **Stub, not functional.** No GPU/vLLM/NIM infrastructure provisioned; template-first policy is enforced regardless. | `services/ve_reach/src/ve_reach/llm_personalization_stub.py` |
| VE Measure | **Real.** Holdout lift, delivery/read/reply tracking, revenue attribution, MLflow run tracking. | `services/ve_measure` |
| VE Console | **Real.** All 9 pages, live 15s polling refresh, no dead pages. | `services/ve_console` |
| Uplift/survival/lookalike/next-event models, SHAP, Evidently drift, multi-clinic productization | **Not built.** Phase 2/3/4 per the roadmap in this doc — no code exists for these yet. | — |

## Opportunity Policies as Data

Opportunity families are defined in separate YAML files under
`policies/opportunities/`. Python code does not contain family-specific rule
or message branches.

The catalog includes every family from the operating model whose method
contains `R` or `D`:

```text
A, B, C, D, E, F, G, H, J, K, L, M, O, P, Q
```

AI-only families `I` and `N` are intentionally excluded. For hybrid methods
such as `D/AI`, this engine owns only the deterministic portion.

All listed families are active. A/C/G use established feature fields. The
other families use governed upstream boolean trigger fields in
`patient_features`; the service named by each policy's
`activation.source_owner` owns the approved derivation of that trigger.

When adding or changing a family:

1. Update its governed source feature or trigger contract.
2. Update the YAML conditions, evidence, priority, consent class, template,
   parameters, and session text.
3. Obtain Meta approval for its WhatsApp template.
4. Rebuild `ve_orchestrator` and `ve_reach`.

```bash
cd ~/velo-engage/infra
docker compose -f docker-compose.dev.yml up -d --build \
  ve_orchestrator ve_reach ve_console
```

The YAML evaluator uses structured operators and never executes expressions
with Python `eval`. See `policies/opportunities/README.md` for the supported
condition format.

All-family development flow, source ownership, migrations, scripts, and NATS
connections are documented in `policies/opportunities/README.md`.
