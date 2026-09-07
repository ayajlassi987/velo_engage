# Builds the incrementally-migrated React frontend (services/ve_console/
# frontend/) into static assets — a separate stage so the final image never
# needs Node at runtime, only the built output. WORKDIR mirrors the real
# repo layout (services/ve_console/frontend, sibling to .../src) so
# vite.config.ts's relative outDir ("../src/ve_console/react_dist") lands
# in the same place it does for a local `npm run build`, not a fragile
# path computed from an arbitrary WORKDIR.
FROM node:22-slim AS frontend
WORKDIR /build/services/ve_console/frontend
COPY services/ve_console/frontend/package.json services/ve_console/frontend/package-lock.json ./
RUN npm install
COPY services/ve_console/frontend/ ./
RUN npm run build

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY services/ve_console/pyproject.toml ./
COPY services/ve_console/src ./src
COPY ml/registry ./ml/registry
COPY libs/ve_clients ./libs/ve_clients
COPY --from=frontend /build/services/ve_console/src/ve_console/react_dist ./src/ve_console/react_dist

RUN uv pip install --system .

CMD ["uvicorn", "ve_console.main:app", "--host", "0.0.0.0", "--port", "8000"]
