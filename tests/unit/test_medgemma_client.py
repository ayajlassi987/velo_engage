"""Mocked at the httpx.Client boundary — no real DGX/model server call.
Protocol mocked here matches the team's own medgemma_server/example_client.py
exactly (confirmed live against their real server, see PROJECT_STATUS.md):
SSE lines prefixed "data:", {"type":"token","text":...} per token,
terminated by a literal "data: [DONE]" line."""

import json

import pytest

import ve_clinical_intel.medgemma_client as mc


class FakeStreamResponse:
    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(self._lines)


class FakeStreamCtx:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self._response

    def __exit__(self, *args):
        return False


class FakeClient:
    def __init__(self, response, captured_calls):
        self._response = response
        self._captured_calls = captured_calls

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def stream(self, method, url, json=None):
        self._captured_calls.append({"method": method, "url": url, "json": json})
        return FakeStreamCtx(self._response)


def _sse_lines(*events, done=True):
    lines = [f"data: {json.dumps(e)}" for e in events]
    if done:
        lines.append("data: [DONE]")
    return lines


def test_extract_structured_data_accumulates_tokens_and_parses_json(monkeypatch):
    payload = {"diagnoses": ["E11"], "medications": [], "procedures": [], "follow_up_recommendations": [], "clinical_risks": []}
    tokens = list(json.dumps(payload))  # one char per token, worst case
    events = [{"type": "token", "text": t} for t in tokens]
    events.append({"type": "done", "tokens_generated": len(tokens), "tokens_per_sec": 50, "elapsed_sec": 1.0})
    response = FakeStreamResponse(_sse_lines(*events))

    captured = []
    monkeypatch.setattr(mc.httpx, "Client", lambda timeout=None: FakeClient(response, captured))

    result = mc.extract_structured_data("Patient has type 2 diabetes.")

    assert result == payload
    assert captured[0]["url"].endswith("/v1/chat/completions")
    assert captured[0]["json"]["stream"] is True
    assert captured[0]["json"]["messages"][0]["role"] == "user"


def test_extract_structured_data_raises_on_invalid_json(monkeypatch):
    events = [{"type": "token", "text": "not valid json"}]
    response = FakeStreamResponse(_sse_lines(*events))
    monkeypatch.setattr(mc.httpx, "Client", lambda timeout=None: FakeClient(response, []))

    with pytest.raises(ValueError, match="not valid JSON"):
        mc.extract_structured_data("some note")


def test_extract_structured_data_raises_on_server_error_event(monkeypatch):
    events = [{"type": "error", "message": "model overloaded"}]
    response = FakeStreamResponse(_sse_lines(*events, done=True))
    monkeypatch.setattr(mc.httpx, "Client", lambda timeout=None: FakeClient(response, []))

    with pytest.raises(RuntimeError, match="MedGemma server reported an error"):
        mc.extract_structured_data("some note")


def test_non_data_lines_are_ignored():
    lines = [": keep-alive comment", "data: " + json.dumps({"type": "token", "text": "{}"}), "data: [DONE]"]
    response = FakeStreamResponse(lines)
    result = mc._accumulate_stream(response)
    assert result == "{}"
