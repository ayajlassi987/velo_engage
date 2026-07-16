# Opportunity family policies

Each YAML file owns one opportunity family. The loader accepts only policies
whose `methods` contain `R` (rule) or `D` (deterministic). AI-only families are
not present in this directory.

Every included family is enabled. A/C/G evaluate established feature fields;
the other families evaluate governed upstream `*_flag` fields. The service
named by `activation.source_owner` owns the approved logic that sets its flag.
The opportunity engine does not infer clinical or commercial eligibility.

The evaluator supports nested `all`/`any` conditions and these operators:
`eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `contains`, `is_null`,
`not_null`, and `days_until_between`.

## How policies connect to the flow

```text
001_initial.sql / 007_policy_family_features.sql
    -> patient_features source fields and governed trigger flags

seed_dummy_patients.py / seed_policy_family_flags.sql
    -> development feature values and matching consent classes

ve_orchestrator.policy_engine
    -> loads every *.yml file, validates it, and evaluates conditions

activities.evaluate_rules
    -> creates deterministic opportunities with YAML evidence and priority

activities.gate_consent
    -> checks the YAML consent_class against the consent table

activities.rank_and_assign_holdout
    -> creates treated/holdout campaigns using the YAML template name

activities.dispatch_treated_to_reach
    -> publishes treated campaigns to campaigns.<clinic>.<family> in NATS

ve_reach.subscriber + ve_reach.sender
    -> loads the same family YAML and renders its template/session message

Meta webhooks + ve_measure
    -> update delivered/read/replied, bookings, attendance, and revenue

ve_console
    -> reads these database records and discovers available families dynamically
```

`scripts/run_rules.py` is the standalone development entry point and uses the
same `policy_engine` as Temporal. `scripts/run_decide.py` also resolves template
names from YAML. The normal production path is the scheduled Temporal workflow;
the standalone scripts are for controlled development only.

## Development data

For an existing database, apply the feature migration and seed one trigger for
each family:

```bash
docker cp infra/migrations/007_policy_family_features.sql \
  ve_postgres:/tmp/007_policy_family_features.sql
docker exec ve_postgres psql -U velo -d velodb \
  -f /tmp/007_policy_family_features.sql

docker cp scripts/seed_policy_family_flags.sql \
  ve_postgres:/tmp/seed_policy_family_flags.sql
docker exec ve_postgres psql -U velo -d velodb \
  -f /tmp/seed_policy_family_flags.sql
```

Then trigger the capped workflow:

```bash
docker exec ve_temporal temporal schedule trigger \
  --address temporal:7233 \
  --schedule-id daily-engagement-schedule
```

The development batch reserves at least one slot per matching family and sends
at most one treated campaign because `DISPATCH_LIMIT=1`.

## WhatsApp templates

After setting a valid Meta token in `services/ve_reach/.env`, create any
missing templates directly from the enabled YAML policies:

```bash
uv run python scripts/sync_whatsapp_templates.py
```

The script is idempotent: existing templates are reported with their current
status, and only missing templates are submitted. Meta must approve each
template before production delivery. Recreate `ve_reach` after changing the
token because Compose reads `.env` when the container starts.
