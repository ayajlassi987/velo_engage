FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY services/ve_clinical_intel/pyproject.toml ./
COPY services/ve_clinical_intel/src ./src

RUN uv pip install --system .

CMD ["uvicorn", "ve_clinical_intel.main:app", "--host", "0.0.0.0", "--port", "8000"]
