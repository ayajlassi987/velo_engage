"""Real-Postgres version of tests/unit/test_feature_store_filter.py's stubbed
test — the actual regression guard for the crowding-out bug (see
feature_store.py's own comment): confirms fetch_patient_features excludes
SYN*/P0xx patient_ids against a genuine Postgres query plan, not just a
recorded SQL string."""

import uuid

from ve_orchestrator.feature_store import fetch_patient_features


def test_fetch_patient_features_excludes_synthetic_and_seed_patients(pg_conn, pg_cursor):
    # Unique per test run, not a fixed constant: fetch_patient_features
    # checks a Redis cache keyed by clinic_id before touching Postgres at
    # all (ve:patient_features:{clinic_id}, 5-minute TTL) — a fixed clinic_id
    # across repeated test runs within that window would let a *previous*
    # run's cached result leak into this one instead of exercising the
    # actual SQL query being tested.
    test_clinic_id = f"test_clinic_integration_{uuid.uuid4().hex[:8]}"
    real_id = f"real_test_{uuid.uuid4().hex[:8]}"
    synthetic_id = f"SYN{uuid.uuid4().hex[:8]}"
    seed_id = f"P0{uuid.uuid4().hex[:6]}"

    # Never committed — visible to the SELECT below within this same
    # transaction, then rolled back by the pg_cursor fixture's teardown,
    # so the real dev database is never actually touched.
    for pid, age in ((real_id, 40), (synthetic_id, 50), (seed_id, 60)):
        pg_cursor.execute(
            "INSERT INTO patient_features (patient_id, clinic_id, age) VALUES (%s, %s, %s)",
            (pid, test_clinic_id, age),
        )

    rows = fetch_patient_features(pg_cursor, test_clinic_id)
    patient_ids = {pid for pid, _ in rows}

    assert real_id in patient_ids
    assert synthetic_id not in patient_ids
    assert seed_id not in patient_ids
