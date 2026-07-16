#!/bin/bash
# fix_and_restart.sh — kills stale workers, clears cache, restarts cleanly

cd ~/velo-engage

echo "▶ Killing all stale Temporal worker processes..."
pkill -f "ve_orchestrator.worker" 2>/dev/null && echo "  ✓ Workers killed" || echo "  No workers running"
sleep 2

echo "▶ Clearing Python bytecode cache..."
find services/ve_orchestrator -name "*.pyc" -delete
find services/ve_orchestrator -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
echo "  ✓ Cache cleared"

echo "▶ Verifying new activities file is in place..."
# Check the return type annotation — slim version returns list[str], old returns list[dict]
if grep -q "async def evaluate_rules() -> list\[str\]" \
     services/ve_orchestrator/src/ve_orchestrator/activities.py; then
  echo "  ✓ Slim activities confirmed (returns list[str])"
else
  echo "  ✗ Wrong activities file — copying now..."
  # If you have the file at repo root:
  cp activities_slim.py \
    services/ve_orchestrator/src/ve_orchestrator/activities.py
  cp workflows_updated.py \
    services/ve_orchestrator/src/ve_orchestrator/workflows.py
  echo "  ✓ Files replaced"
fi

echo "▶ Verifying workflows file is in place..."
if grep -q "len(opportunity_ids)" \
     services/ve_orchestrator/src/ve_orchestrator/workflows.py; then
  echo "  ✓ Updated workflows confirmed"
fi

mkdir -p logs

echo "▶ Starting fresh Temporal worker..."
cd services/ve_orchestrator
uv run python -m ve_orchestrator.worker \
  > ~/velo-engage/logs/temporal_worker.log 2>&1 &
WORKER_PID=$!
echo "  ✓ Worker started (PID $WORKER_PID)"
cd ~/velo-engage

echo "▶ Waiting 5 seconds for worker to connect to Temporal..."
sleep 5

# Confirm worker is actually connected
if grep -q "Worker started" logs/temporal_worker.log 2>/dev/null; then
  echo "  ✓ Worker connected"
else
  echo "  Worker log (last 5 lines):"
  tail -5 logs/temporal_worker.log 2>/dev/null
fi

echo "▶ Triggering workflow..."
cd services/ve_orchestrator
uv run python -m ve_orchestrator.trigger