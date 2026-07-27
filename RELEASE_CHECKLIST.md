# Velo Engage Phase 1 Release Checklist

Run commands from `infra/` unless noted otherwise.

## Infrastructure

```bash
docker compose -f docker-compose.dev.yml ps
```

- Postgres, NATS, Temporal, `ve_orchestrator`, `ve_measure`, and `ve_console` are running.
- `ve_console` reports healthy at `http://localhost:8002/health`.

## Temporal and worker

```bash
docker exec ve_temporal temporal schedule list --address temporal:7233
docker logs --tail 50 ve_orchestrator
```

- `daily-engagement-schedule-{clinic_id}` is active for every clinic in the `clinics` table (one per active clinic — see `ve_orchestrator/schedules.py`).
- The worker listens on `velo-engage-task-queue`.

## Opportunities, consent, and holdout

```bash
docker exec ve_postgres psql -U velo -d velodb -c \
  "SELECT COUNT(*) FROM opportunities;"
docker exec ve_postgres psql -U velo -d velodb -c \
  "SELECT treatment_arm, COUNT(*) FROM campaigns GROUP BY treatment_arm;"
```

- Opportunities exist and all workflow candidates passed through the consent activity.
- Campaigns include treated and holdout arms.

## Reach and outcomes

```bash
docker exec ve_postgres psql -U velo -d velodb -c \
  "SELECT campaign_id, delivered, read, replied, booked, attended, revenue FROM outcomes;"
```

- WhatsApp delivery/read values reflect Meta webhook callbacks.
- Confirmed and completed appointment events set booked and attended.

## Booking and revenue attribution

```bash
docker exec ve_postgres psql -U velo -d velodb -c \
  "SELECT booking_id, campaign_id, status FROM bookings;"
docker exec ve_postgres psql -U velo -d velodb -c \
  "SELECT invoice_id, campaign_id, amount, currency, paid FROM revenue_attributions;"
```

- Bookings are linked by patient, clinic, and the 30-day campaign window.
- Paid billing events are linked through a booking and reflected in outcomes revenue.

## Console

Open `http://localhost:8002` and verify Opportunities, Campaigns, WhatsApp,
Revenue, and Holdout pages display current metrics.

## Holdout safety gate

```sql
SELECT *
FROM campaigns
WHERE treatment_arm = 'holdout'
  AND dispatched_at IS NOT NULL;
```

Expected result: **0 rows**. Any returned row blocks release.
