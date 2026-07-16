#!/bin/bash
# start_all.sh — launches the full automated pipeline in the correct order
# Run from repo root: bash start_all.sh

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "════════════════════════════════════════════════════"
echo "  Velo Engage — Full Automated Pipeline Startup"
echo "════════════════════════════════════════════════════"

# ── 1. Infrastructure ─────────────────────────────────────────────────────────
echo ""
echo "▶ Step 1: Starting infra containers..."
cd infra && docker compose -f docker-compose.dev.yml up -d
cd "$ROOT"

echo "  Waiting for Postgres to be healthy..."
until docker exec ve_postgres pg_isready -U velo -d velodb > /dev/null 2>&1; do
  sleep 2
done
echo "  ✓ Postgres healthy"

echo "  Waiting for NATS..."
until curl -sf http://localhost:8222/healthz > /dev/null 2>&1; do
  sleep 2
done
echo "  ✓ NATS healthy"

# ── 2. Apply migration 003 (idempotent — safe to re-run) ─────────────────────
echo ""
echo "▶ Step 2: Applying migration 003 (ML columns)..."
docker exec -i ve_postgres psql -U velo -d velodb \
  < infra/migrations/003_patient_features_ml_columns.sql \
  && echo "  ✓ Migration applied"

# ── 3. Seed patients (only if staging_patients is empty) ─────────────────────
echo ""
echo "▶ Step 3: Checking patient data..."
COUNT=$(docker exec ve_postgres psql -U velo -d velodb -tAc \
  "SELECT count(*) FROM staging_patients;")
if [ "$COUNT" -eq "0" ]; then
  echo "  No patients found — seeding..."
  uv run python scripts/seed_dummy_patients.py
else
  echo "  ✓ $COUNT patients already in DB — skipping seed"
fi

# ── 4. Launch ve_reach in background ─────────────────────────────────────────
echo ""
echo "▶ Step 4: Starting ve_reach (WhatsApp sender)..."
cd services/ve_reach
uv run uvicorn ve_reach.main:app \
  --host 0.0.0.0 --port 8001 --log-level info \
  > "$ROOT/logs/ve_reach.log" 2>&1 &
VE_REACH_PID=$!
echo "  ✓ ve_reach started (PID $VE_REACH_PID) — logs: logs/ve_reach.log"
cd "$ROOT"

# Wait for ve_reach to be up
sleep 3
until curl -sf http://localhost:8001/health > /dev/null 2>&1; do
  echo "  Waiting for ve_reach..."
  sleep 2
done
echo "  ✓ ve_reach healthy"

# ── 5. Launch Temporal worker in background ───────────────────────────────────
echo ""
echo "▶ Step 5: Starting Temporal worker..."
cd services/ve_orchestrator
uv run python -m ve_orchestrator.worker \
  > "$ROOT/logs/temporal_worker.log" 2>&1 &
WORKER_PID=$!
echo "  ✓ Temporal worker started (PID $WORKER_PID) — logs: logs/temporal_worker.log"
cd "$ROOT"

sleep 3

# ── 6. Trigger one workflow run ───────────────────────────────────────────────
echo ""
echo "▶ Step 6: Triggering daily engagement workflow..."
cd services/ve_orchestrator
uv run python -m ve_orchestrator.trigger
cd "$ROOT"

# ── 7. Tail ve_reach logs to watch WhatsApp sends ────────────────────────────
echo ""
echo "════════════════════════════════════════════════════"
echo "  Pipeline running. Watching ve_reach sends..."
echo "  Temporal UI: http://localhost:8080"
echo "  Press Ctrl+C to stop tailing (services keep running)"
echo "════════════════════════════════════════════════════"
echo ""
tail -f logs/ve_reach.log