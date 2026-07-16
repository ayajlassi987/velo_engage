FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# libgomp1 provides libgomp.so.1, required by LightGBM's compiled extension
# (used inside the velo_engage_booking_propensity sklearn pipeline).
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY services/ve_orchestrator/pyproject.toml services/ve_orchestrator/README.md ./
COPY services/ve_orchestrator/src ./src
COPY policies/opportunities ./policies/opportunities
COPY ml/registry ./ml/registry
COPY libs/ve_clients ./libs/ve_clients

RUN uv pip install --system .

ENV OPPORTUNITY_POLICY_DIR=/app/policies/opportunities

CMD ["python", "-m", "ve_orchestrator.worker"]
