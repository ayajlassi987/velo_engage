"""Real-Postgres regression test for Phase 2b's batching of gate_consent
(consent check + cooldown/frequency check, previously one SELECT per
opportunity/patient, now one ANY(...) query and one GROUP BY query) —
confirms identical pass/block behavior against a genuine Postgres
connection, not just the mocked unit-level query-string assertions.

gate_consent opens its own DB connection internally (activities.py::_db),
separate from the pg_conn/pg_cursor fixtures — so unlike test_feature_store,
this test must actually commit its fixtures for gate_consent's own
connection to see them, and clean up explicitly afterward.
"""

import asyncio
import uuid

import pytest

from ve_orchestrator.activities import gate_consent

TEST_CLINIC_ID = "test_clinic_gate_consent"


@pytest.fixture
def seeded_opportunities(pg_conn, pg_cursor):
    consented_patient = f"consented_{uuid.uuid4().hex[:8]}"
    blocked_patient = f"blocked_{uuid.uuid4().hex[:8]}"
    consented_opp = f"opp_{uuid.uuid4().hex[:12]}"
    blocked_opp = f"opp_{uuid.uuid4().hex[:12]}"

    pg_cursor.execute(
        """INSERT INTO opportunities (opportunity_id, patient_id, clinic_id, family, consent_class, priority_score)
           VALUES (%s,%s,%s,'C','care_recall',0.9), (%s,%s,%s,'C','care_recall',0.9)""",
        (consented_opp, consented_patient, TEST_CLINIC_ID, blocked_opp, blocked_patient, TEST_CLINIC_ID),
    )
    pg_cursor.execute(
        """INSERT INTO consent (patient_id, clinic_id, consent_class, channel)
           VALUES (%s,%s,'care_recall','whatsapp')""",
        (consented_patient, TEST_CLINIC_ID),
    )
    pg_conn.commit()

    yield {
        "consented_opp": consented_opp, "blocked_opp": blocked_opp,
        "consented_patient": consented_patient, "blocked_patient": blocked_patient,
    }

    pg_cursor.execute("DELETE FROM consent WHERE clinic_id=%s", (TEST_CLINIC_ID,))
    pg_cursor.execute("DELETE FROM campaigns WHERE clinic_id=%s", (TEST_CLINIC_ID,))
    pg_cursor.execute("DELETE FROM opportunities WHERE clinic_id=%s", (TEST_CLINIC_ID,))
    pg_conn.commit()


def test_gate_consent_allows_patient_with_consent_blocks_patient_without(seeded_opportunities):
    allowed = asyncio.run(gate_consent([
        seeded_opportunities["consented_opp"], seeded_opportunities["blocked_opp"],
    ]))
    assert seeded_opportunities["consented_opp"] in allowed
    assert seeded_opportunities["blocked_opp"] not in allowed


def test_gate_consent_empty_input_returns_empty():
    assert asyncio.run(gate_consent([])) == []
