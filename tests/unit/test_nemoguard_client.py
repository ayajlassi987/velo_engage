"""Mocked at the httpx.Client boundary. Prompt/output schema confirmed
live against the real NemoGuard NIM on the DGX (JSON verdict, "User
Safety" key) — see nemoguard_client.py's own docstring."""

import ve_clinical_intel.nemoguard_client as nc


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
    def __init__(self, response=None, raise_exc=None):
        self._response = response
        self._raise_exc = raise_exc

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json=None):
        if self._raise_exc:
            raise self._raise_exc
        return self._response

    def get(self, url):
        if self._raise_exc:
            raise self._raise_exc
        return self._response


def _chat_response(content: str):
    return FakeResponse({"choices": [{"message": {"content": content}}]})


def test_explicit_safe_verdict_passes(monkeypatch):
    monkeypatch.setattr(nc.httpx, "Client", lambda timeout=None: FakeClient(_chat_response('{"User Safety": "safe"}')))
    assert nc.check_safety("Patient reports mild headache.") is True


def test_explicit_unsafe_verdict_blocks(monkeypatch):
    monkeypatch.setattr(nc.httpx, "Client", lambda timeout=None: FakeClient(_chat_response('{"User Safety": "unsafe", "Safety Categories": "PII/Privacy"}')))
    assert nc.check_safety("some text") is False


def test_unauthorized_advice_only_does_not_block(monkeypatch):
    monkeypatch.setattr(nc.httpx, "Client", lambda timeout=None: FakeClient(_chat_response('{"User Safety": "unsafe", "Safety Categories": "Unauthorized Advice"}')))
    assert nc.check_safety("Recommend ibuprofen 400mg.") is True


def test_unauthorized_advice_plus_real_category_still_blocks(monkeypatch):
    monkeypatch.setattr(nc.httpx, "Client", lambda timeout=None: FakeClient(_chat_response('{"User Safety": "unsafe", "Safety Categories": "Unauthorized Advice, Violence"}')))
    assert nc.check_safety("some text") is False


def test_unsafe_with_no_categories_blocks_fail_safe(monkeypatch):
    monkeypatch.setattr(nc.httpx, "Client", lambda timeout=None: FakeClient(_chat_response('{"User Safety": "unsafe"}')))
    assert nc.check_safety("some text") is False


def test_ambiguous_response_blocks_fail_safe(monkeypatch):
    monkeypatch.setattr(nc.httpx, "Client", lambda timeout=None: FakeClient(_chat_response("I'm not sure, could go either way")))
    assert nc.check_safety("some text") is False


def test_network_error_blocks_fail_safe(monkeypatch):
    monkeypatch.setattr(nc.httpx, "Client", lambda timeout=None: FakeClient(raise_exc=ConnectionError("unreachable")))
    assert nc.check_safety("some text") is False


def test_malformed_response_shape_blocks_fail_safe(monkeypatch):
    bad_response = FakeResponse({"unexpected": "shape"})  # no "choices" key
    monkeypatch.setattr(nc.httpx, "Client", lambda timeout=None: FakeClient(bad_response))
    assert nc.check_safety("some text") is False
