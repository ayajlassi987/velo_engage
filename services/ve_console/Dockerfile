FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY services/ve_console/pyproject.toml ./
COPY services/ve_console/src ./src
COPY ml/registry ./ml/registry
COPY libs/ve_clients ./libs/ve_clients

RUN uv pip install --system .

CMD ["uvicorn", "ve_console.main:app", "--host", "0.0.0.0", "--port", "8000"]
