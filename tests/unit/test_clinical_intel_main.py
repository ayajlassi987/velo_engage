"""Orchestration tests for process_patient() — mocks _fetch_clinical_notes,
the ve_connect HTTP upsert call, and both model clients, so this never needs
a real DGX/Postgres/ve_connect. Covers the three real outcomes per note:
safety-blocked, successfully extracted, and errored (never crashes the whole
patient's processing — see main.py's own comment on why the try/except is
scoped per-note).

Upsert goes through ve_connect's HTTP API (POST /clinical-extractions), not
a direct DB connection — the DGX has no route to raw Postgres (see
main.py's module docstring) — so httpx.Client is the mock boundary here,
same pattern as nemoguard_client's tests."""

import ve_clinical_intel.main as main


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class FakeClient:
    def __init__(self, posts):
        self.posts = posts

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json=None):
        self.posts.append((url, json))
        return FakeResponse({"extraction_id": f"extracted-{len(self.posts)}"})


def _note(doc_id="doc1", text="Patient has type 2 diabetes."):
    return {"document_reference_id": doc_id, "content_type": "text/html", "note_date": "2026-01-01", "text": text}


def test_safety_blocked_note_never_reaches_medgemma(monkeypatch):
    posts = []
    monkeypatch.setattr(main.httpx, "Client", lambda timeout=None: FakeClient(posts))
    monkeypatch.setattr(main, "_fetch_clinical_notes", lambda pid: ([_note()], None))
    monkeypatch.setattr(main.nemoguard_client, "check_safety", lambda text: False)

    called = {"medgemma": False}
    def fake_extract(text):
        called["medgemma"] = True
        return {}
    monkeypatch.setattr(main.medgemma_client, "extract_structured_data", fake_extract)

    result = main.process_patient("P001")

    assert called["medgemma"] is False
    assert result["blocked"] == 1
    assert result["processed"] == 0
    assert posts == []  # blocked notes are never upserted


def test_successful_extraction_upserts_and_counts_processed(monkeypatch):
    posts = []
    monkeypatch.setattr(main.httpx, "Client", lambda timeout=None: FakeClient(posts))
    monkeypatch.setattr(main, "_fetch_clinical_notes", lambda pid: ([_note()], None))
    monkeypatch.setattr(main.nemoguard_client, "check_safety", lambda text: True)
    monkeypatch.setattr(main.medgemma_client, "extract_structured_data", lambda text: {
        "diagnoses": ["E11"], "medications": [], "procedures": [],
        "follow_up_recommendations": [], "clinical_risks": [],
    })

    result = main.process_patient("P001")

    assert result["processed"] == 1
    assert result["blocked"] == 0
    assert result["errors"] == 0
    assert result["extraction_ids"] == ["extracted-1"]
    assert len(posts) == 1
    url, payload = posts[0]
    assert url.endswith("/clinical-extractions")
    assert payload["document_reference_id"] == "doc1"
    assert payload["diagnoses"] == ["E11"]
    assert payload["safety_check_passed"] is True


def test_malformed_note_missing_text_counts_as_error_not_crash(monkeypatch):
    posts = []
    monkeypatch.setattr(main.httpx, "Client", lambda timeout=None: FakeClient(posts))
    malformed_note = {"document_reference_id": "doc1", "note_date": "2026-01-01"}  # no "text" key
    monkeypatch.setattr(main, "_fetch_clinical_notes", lambda pid: ([malformed_note, _note("doc2")], None))
    monkeypatch.setattr(main.nemoguard_client, "check_safety", lambda text: True)
    monkeypatch.setattr(main.medgemma_client, "extract_structured_data", lambda text: {
        "diagnoses": [], "medications": [], "procedures": [], "follow_up_recommendations": [], "clinical_risks": [],
    })

    result = main.process_patient("P001")

    # The malformed note errors, but the second (valid) note still processes —
    # confirms the try/except is scoped per-note, not around the whole loop.
    assert result["errors"] == 1
    assert result["processed"] == 1
    assert len(posts) == 1


def test_search_failure_is_distinguishable_from_genuinely_zero_notes(monkeypatch):
    # The real bug this guards against: an Epic auth failure (expired
    # interactive OAuth token, invalid_grant on refresh) made
    # _pull_clinical_notes return an empty list identically to a patient
    # with genuinely zero clinical notes — every real patient showed
    # "notes_found: 0" during a token outage, indistinguishable from
    # "confirmed no notes exist." search_error must survive into the
    # final result even when notes_found is 0.
    posts = []
    monkeypatch.setattr(main.httpx, "Client", lambda timeout=None: FakeClient(posts))
    monkeypatch.setattr(
        main, "_fetch_clinical_notes",
        lambda pid: ([], "DocumentReference search unavailable for P001: invalid_grant"),
    )

    result = main.process_patient("P001")

    assert result["notes_found"] == 0
    assert result["search_error"] == "DocumentReference search unavailable for P001: invalid_grant"
    assert posts == []


def test_medgemma_failure_counts_as_error_and_continues(monkeypatch):
    posts = []
    monkeypatch.setattr(main.httpx, "Client", lambda timeout=None: FakeClient(posts))
    monkeypatch.setattr(main, "_fetch_clinical_notes", lambda pid: ([_note("doc1"), _note("doc2")], None))
    monkeypatch.setattr(main.nemoguard_client, "check_safety", lambda text: True)

    def flaky_extract(text):
        raise ValueError("MedGemma response was not valid JSON")
    monkeypatch.setattr(main.medgemma_client, "extract_structured_data", flaky_extract)

    result = main.process_patient("P001")

    assert result["errors"] == 2
    assert result["processed"] == 0
