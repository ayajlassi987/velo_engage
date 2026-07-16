FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY services/ve_measure/pyproject.toml ./
COPY services/ve_measure/src ./src
COPY infra/migrations/002_measure.sql ./migrations/002_measure.sql
COPY libs/ve_clients ./libs/ve_clients

RUN uv pip install --system .

CMD ["python", "-m", "ve_measure.booking_listener"]
