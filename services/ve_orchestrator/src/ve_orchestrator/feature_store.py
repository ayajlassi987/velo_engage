"""VE Store — online feature cache.

Postgres `patient_features` is the offline/authoritative store. This module
adds the online half: a short-TTL Redis cache in front of the per-clinic
feature read that `evaluate_rules` does on every workflow run, so a busy
clinic doesn't re-scan the full cohort from Postgres on every trigger within
the TTL window.

Never a hard dependency — any Redis error falls back to a direct Postgres
read so a cache outage can't break detection.
"""

import json
import logging
import os

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
FEATURE_CACHE_TTL_SECONDS = int(os.getenv("FEATURE_CACHE_TTL_SECONDS", 300))

_redis_client: redis.Redis | None = None


def _client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
    return _redis_client


def fetch_patient_features(cur, clinic_id: str) -> list[tuple[str, dict]]:
    """Returns [(patient_id, features_dict), ...] for a clinic, serving from
    the Redis online cache when fresh and falling back to Postgres (via the
    given cursor) on a cache miss or any Redis error."""
    cache_key = f"ve:patient_features:{clinic_id}"

    try:
        cached = _client().get(cache_key)
        if cached is not None:
            logger.info(f"feature_store: cache hit for {clinic_id}")
            payload = json.loads(cached)
            return [(row["patient_id"], row["features"]) for row in payload]
    except Exception as exc:
        logger.warning(f"feature_store: Redis unavailable ({exc}) — reading Postgres directly")

    # Excludes the synthetic/seed demo population (SYN*, P0xx patient_ids —
    # scripts/seed_synthetic_phase1.py and seed_dummy_patients.py) from live
    # rule evaluation. Real Epic patient_ids are Epic FHIR IDs and never
    # match either prefix. Without this, ~20,000 synthetic patients compete
    # for the same WORKFLOW_BATCH_LIMIT every run and drown out the much
    # smaller real Epic population — confirmed live: a full pipeline run
    # found real opportunities for real Epic patients but zero of them
    # became campaigns, entirely crowded out by synthetic volume. The
    # existing synthetic rows/history are untouched — this only stops them
    # from being re-evaluated going forward.
    cur.execute("""
        SELECT patient_id, to_jsonb(pf) - 'patient_id' - 'clinic_id'
        FROM patient_features pf
        WHERE clinic_id = %s AND patient_id NOT LIKE 'SYN%%' AND patient_id NOT LIKE 'P0%%'
    """, (clinic_id,))
    rows = [(patient_id, features) for patient_id, features in cur.fetchall()]

    try:
        payload = [{"patient_id": pid, "features": features} for pid, features in rows]
        _client().set(cache_key, json.dumps(payload, default=str), ex=FEATURE_CACHE_TTL_SECONDS)
    except Exception as exc:
        logger.warning(f"feature_store: could not populate Redis cache ({exc})")

    return rows
