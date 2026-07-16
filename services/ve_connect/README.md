# ve_connect

`ve_connect` authorizes Velo Engage against an Epic SMART-on-FHIR app, pulls
FHIR cohorts, maps them into `staging_patients` and `patient_features`, and
feeds the opportunity-policy workflow.

## Configure Epic SMART

Create the local environment file:

```bash
cd ~/velo-engage
cp services/ve_connect/.env.example services/ve_connect/.env
```

Set these values using the Epic app registration:

```dotenv
EPIC_CLIENT_ID=your_client_id
EPIC_REDIRECT_URI=http://localhost:8003/auth/callback
EPIC_SCOPES="your approved SMART scopes"
EPIC_FHIR_BASE=your Epic FHIR R4 base URL
```

`EPIC_CLIENT_SECRET` is needed only when the registered Epic app requires one.
The redirect URI must match the app registration exactly, including scheme,
host, port, path, and trailing slash behavior.

By default, OAuth endpoints are loaded from:

```text
<EPIC_FHIR_BASE>/.well-known/smart-configuration
```

Set `EPIC_AUTH_URL` and `EPIC_TOKEN_URL` only when the Epic environment does
not expose SMART discovery or when its registration gives explicit endpoints.

## Prepare PostgreSQL

```bash
docker cp infra/migrations/002_epic_tokens.sql \
  ve_postgres:/tmp/002_epic_tokens.sql
docker exec ve_postgres psql -U velo -d velodb \
  -f /tmp/002_epic_tokens.sql
```

## Start locally

```bash
cd ~/velo-engage/services/ve_connect
uv run uvicorn ve_connect.main:app \
  --host 0.0.0.0 \
  --port 8003 \
  --reload
```

Check configuration before opening Epic login:

```bash
curl http://localhost:8003/auth/config
curl http://localhost:8003/health
```

When `configured` is `true`, open:

```text
http://localhost:8003/auth/login
```

After Epic redirects to `/auth/callback`, check:

```bash
curl http://localhost:8003/auth/status
```

## Pull a cohort

```bash
curl -X POST "http://localhost:8003/pull-cohort?max_patients=100"
```

The connection into the engagement flow is:

```text
Epic FHIR
  -> ve_connect.fhir_client
  -> ve_connect.mapper
  -> ve_connect.adapter
  -> staging_patients + patient_features
  -> YAML opportunity policies
  -> Temporal campaigns
  -> VE Reach
```

## Configuration errors

If `/auth/login` returns HTTP `503`, read the `missing` list and populate those
variables in `services/ve_connect/.env`. The service no longer constructs
redirects containing `None`.
