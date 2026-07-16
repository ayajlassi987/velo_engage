FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY services/ve_connect/pyproject.toml services/ve_connect/README.md ./
COPY services/ve_connect/src ./src
COPY libs/ve_clients ./libs/ve_clients

RUN uv pip install --system .

CMD ["uvicorn", "ve_connect.main:app", "--host", "0.0.0.0", "--port", "8000"]
