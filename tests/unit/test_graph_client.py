"""Guards Phase 2c's batching of clinical_recall_due: previously
evaluate_rules opened one new Neo4j session and ran up to 2 Cypher queries
per patient for family B — the worst-scaling piece of the daily pipeline.
clinical_recall_due_batch replaces that with one session, at most 2 queries
total, regardless of patient count. Mocked at the session level — no real
Neo4j needed."""

from datetime import date

from ve_orchestrator.graph_client import clinical_recall_due, clinical_recall_due_batch

TODAY = date(2026, 7, 16)


class FakeSession:
    def __init__(self, condition_rows, age_rows):
        self.condition_rows = condition_rows
        self.age_rows = age_rows
        self.queries_run = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, query, **kwargs):
        self.queries_run.append((query, kwargs))
        if "UNWIND $patients" in query and "REQUIRES_FOLLOWUP" in query:
            return self.condition_rows
        if "UNWIND $patients" in query and "SCREENING_DUE" in query:
            return self.age_rows
        return []


class FakeDriver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session


def _row(**kwargs):
    return dict(kwargs)


def test_batch_returns_none_for_patient_with_no_overdue_recall(monkeypatch):
    import ve_orchestrator.graph_client as gc

    session = FakeSession(condition_rows=[], age_rows=[])
    monkeypatch.setattr(gc, "_driver", lambda: FakeDriver(session))

    patients = [{"id": "P1", "condition_codes": ["E11"], "age": 45, "days_since_last_visit": 30}]
    results = clinical_recall_due_batch(patients, TODAY)

    assert results == {"P1": None}


def test_batch_picks_most_overdue_across_condition_and_age_candidates(monkeypatch):
    import ve_orchestrator.graph_client as gc

    condition_rows = [
        _row(patient_id="P1", condition_code="E11", condition_name="Diabetes", service="Endo follow-up",
             interval_days=180, evidence_source="ADA", specialty="Endocrinology"),
    ]
    age_rows = [
        _row(patient_id="P1", condition_code=None, condition_name="age-based screening", service="Colonoscopy",
             interval_days=365, evidence_source="USPSTF", specialty="GI"),
    ]
    session = FakeSession(condition_rows=condition_rows, age_rows=age_rows)
    monkeypatch.setattr(gc, "_driver", lambda: FakeDriver(session))

    patients = [{"id": "P1", "condition_codes": ["E11"], "age": 55, "days_since_last_visit": 400}]
    results = clinical_recall_due_batch(patients, TODAY)

    # Both are overdue (400 > 180 and 400 > 365); the diabetes follow-up is
    # more overdue (400-180=220 vs 400-365=35), so it should win.
    assert results["P1"]["service"] == "Endo follow-up"
    assert results["P1"]["overdue_by_days"] == 220


def test_batch_groups_results_correctly_across_multiple_patients(monkeypatch):
    import ve_orchestrator.graph_client as gc

    condition_rows = [
        _row(patient_id="P1", condition_code="E11", condition_name="Diabetes", service="Endo follow-up",
             interval_days=180, evidence_source="ADA", specialty="Endocrinology"),
        _row(patient_id="P2", condition_code="I10", condition_name="Hypertension", service="BP check",
             interval_days=90, evidence_source="AHA", specialty="Cardiology"),
    ]
    session = FakeSession(condition_rows=condition_rows, age_rows=[])
    monkeypatch.setattr(gc, "_driver", lambda: FakeDriver(session))

    patients = [
        {"id": "P1", "condition_codes": ["E11"], "age": None, "days_since_last_visit": 200},
        {"id": "P2", "condition_codes": ["I10"], "age": None, "days_since_last_visit": 50},  # not overdue yet
    ]
    results = clinical_recall_due_batch(patients, TODAY)

    assert results["P1"]["service"] == "Endo follow-up"
    assert results["P2"] is None  # 50 days < 90-day interval, not due


def test_batch_makes_at_most_two_queries_regardless_of_patient_count(monkeypatch):
    import ve_orchestrator.graph_client as gc

    session = FakeSession(condition_rows=[], age_rows=[])
    monkeypatch.setattr(gc, "_driver", lambda: FakeDriver(session))

    patients = [
        {"id": f"P{i}", "condition_codes": ["E11"], "age": 40, "days_since_last_visit": 100}
        for i in range(50)
    ]
    clinical_recall_due_batch(patients, TODAY)

    # One UNWIND query for conditions, one for age bands — not one per patient.
    assert len(session.queries_run) == 2


def test_patient_with_no_days_since_last_visit_is_skipped_not_queried(monkeypatch):
    import ve_orchestrator.graph_client as gc

    session = FakeSession(condition_rows=[], age_rows=[])
    monkeypatch.setattr(gc, "_driver", lambda: FakeDriver(session))

    patients = [{"id": "P1", "condition_codes": ["E11"], "age": 45, "days_since_last_visit": None}]
    results = clinical_recall_due_batch(patients, TODAY)

    assert results == {"P1": None}
    # Neither query should include P1 since it can never be "overdue" without
    # a days_since_last_visit to compare against.
    for _, kwargs in session.queries_run:
        patient_ids = [p["id"] for p in kwargs.get("patients", [])]
        assert "P1" not in patient_ids


def test_single_patient_wrapper_matches_batch_behavior(monkeypatch):
    import ve_orchestrator.graph_client as gc

    condition_rows = [
        _row(patient_id="_single", condition_code="E11", condition_name="Diabetes", service="Endo follow-up",
             interval_days=180, evidence_source="ADA", specialty="Endocrinology"),
    ]
    session = FakeSession(condition_rows=condition_rows, age_rows=[])
    monkeypatch.setattr(gc, "_driver", lambda: FakeDriver(session))

    result = clinical_recall_due(condition_codes=["E11"], age=None, days_since_last_visit=250, as_of=TODAY)

    assert result["service"] == "Endo follow-up"
    assert result["overdue_by_days"] == 70
