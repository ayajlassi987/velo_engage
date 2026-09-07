FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
# pathway_engine.py's parents[4]-based default only resolves correctly in
# local dev (services/ve_treatment_planner/src/.../pathway_engine.py, 4
# levels below repo root); set it explicitly here rather than replicate
# ve_connect's multi-candidate-path search for one fixed, known-at-build-
# time location.
ENV DENTAL_PATHWAY_DIR=/app/policies/dental_pathways

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY services/ve_treatment_planner/pyproject.toml services/ve_treatment_planner/README.md ./
COPY services/ve_treatment_planner/src ./src
COPY libs/ve_clients ./libs/ve_clients
COPY policies/dental_pathways ./policies/dental_pathways

RUN uv pip install --system .

# Two processes can run from this image: the FastAPI front door (default)
# and the Temporal worker (services/ve_treatment_planner/worker — see
# docker-compose.dev.yml, which runs a second container from this same
# image with the worker command instead).
CMD ["uvicorn", "ve_treatment_planner.main:app", "--host", "0.0.0.0", "--port", "8000"]
