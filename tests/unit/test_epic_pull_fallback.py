"""pull_epic_data (ve_orchestrator/activities.py) must never let a slow/
unreachable Epic connection take down the whole daily pipeline for the
much larger existing patient population — it's the first activity in
DailyEngagementWorkflow, and everything downstream still needs to run even
if today's Epic refresh fails. Mocks urllib at the boundary; no real
network call."""

import asyncio
import json
import urllib.error

from ve_orchestrator.activities import pull_epic_data


def test_successful_pull_returns_parsed_result(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"status": "complete", "processed": 7}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: FakeResponse())

    result = asyncio.run(pull_epic_data())

    assert result == {"status": "complete", "processed": 7}


def test_connection_failure_degrades_gracefully_not_raises(monkeypatch):
    def raise_url_error(req, timeout):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr("urllib.request.urlopen", raise_url_error)

    result = asyncio.run(pull_epic_data())

    assert result["status"] == "failed"
    assert "Connection refused" in result["error"]


def test_malformed_json_response_degrades_gracefully(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"not valid json"

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: FakeResponse())

    result = asyncio.run(pull_epic_data())

    assert result["status"] == "failed"


def test_timeout_degrades_gracefully(monkeypatch):
    def raise_timeout(req, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", raise_timeout)

    result = asyncio.run(pull_epic_data())

    assert result["status"] == "failed"
