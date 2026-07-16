FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY services/ve_reach/pyproject.toml ./
COPY services/ve_reach/src ./src
COPY policies/opportunities ./policies/opportunities
COPY ml/registry ./ml/registry
COPY libs/ve_clients ./libs/ve_clients

RUN uv pip install --system .

ENV OPPORTUNITY_POLICY_DIR=/app/policies/opportunities

CMD ["uvicorn", "ve_reach.main:app", "--host", "0.0.0.0", "--port", "8000"]
