"""ve_reach's Epic-auth proxy routes (/auth/login, /auth/callback, /) —
forwards to ve_connect's real handlers so the one ngrok tunnel (pointed at
ve_reach for WhatsApp webhooks) can also serve Epic's OAuth login/callback,
without ever needing to be manually swapped between the two. Mocked at the
httpx.AsyncClient boundary, no real network call to ve_connect — matches
test_sender_http.py/test_email_channel.py's mocking pattern, just async.

Route handlers are called directly (asyncio.run(...)), not through a real
ASGI request cycle — importing ve_reach.main has no side effects at import
time (the subscriber only starts via the app's lifespan, which TestClient
would trigger and this deliberately avoids, same reasoning as
test_clinical_intel_main.py calling process_patient() directly)."""

import asyncio
import json

import httpx

import ve_reach.main as main


class FakeAsyncResponse:
    def __init__(self, status_code=200, json_data=None, headers=None):
        self.status_code = status_code
        self._json = json_data
        self.headers = headers or {}

    def json(self):
        return self._json


class FakeAsyncClient:
    def __init__(self, response, requests):
        self._response = response
        self._requests = requests

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None):
        self._requests.append({"url": url, "params": params})
        return self._response


def test_login_redirects_to_ve_connects_location_header(monkeypatch):
    requests = []
    fake_response = FakeAsyncResponse(
        status_code=307,
        headers={"location": "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize?client_id=abc"},
    )
    monkeypatch.setattr(
        main.httpx, "AsyncClient",
        lambda follow_redirects=None, timeout=None: FakeAsyncClient(fake_response, requests),
    )

    response = asyncio.run(main.proxy_epic_login())

    assert response.status_code == 307
    assert response.headers["location"] == fake_response.headers["location"]
    assert requests[0]["url"] == "http://ve_connect:8000/auth/login"


def test_callback_forwards_code_and_state_and_relays_json_body(monkeypatch):
    requests = []
    fake_response = FakeAsyncResponse(
        status_code=200,
        json_data={"status": "authorized", "expires_in": 3600, "message": "..."},
    )
    monkeypatch.setattr(
        main.httpx, "AsyncClient",
        lambda timeout=None: FakeAsyncClient(fake_response, requests),
    )

    response = asyncio.run(main.proxy_epic_callback(code="auth-code-123", state="state-abc"))

    assert response.status_code == 200
    assert json.loads(response.body) == {"status": "authorized", "expires_in": 3600, "message": "..."}
    assert requests[0]["url"] == "http://ve_connect:8000/auth/callback"
    assert requests[0]["params"] == {"code": "auth-code-123", "state": "state-abc"}


def test_root_path_also_proxies_to_ve_connects_callback(monkeypatch):
    # Epic's registered redirect_uri has no path at all, so its redirect can
    # land on bare "/" instead of "/auth/callback" — this must behave
    # identically to the dedicated callback route.
    requests = []
    fake_response = FakeAsyncResponse(status_code=200, json_data={"status": "authorized"})
    monkeypatch.setattr(
        main.httpx, "AsyncClient",
        lambda timeout=None: FakeAsyncClient(fake_response, requests),
    )

    response = asyncio.run(main.proxy_epic_root(code="auth-code-123", state="state-abc"))

    assert response.status_code == 200
    assert requests[0]["url"] == "http://ve_connect:8000/auth/callback"


def test_callback_relays_ve_connects_error_status(monkeypatch):
    # ve_connect returns 502 with Epic's real rejection body on a failed
    # token exchange — the proxy must relay that status, not swallow it
    # into a false 200.
    requests = []
    fake_response = FakeAsyncResponse(
        status_code=502,
        json_data={"detail": {"message": "Epic rejected the token exchange", "epic_status": 400}},
    )
    monkeypatch.setattr(
        main.httpx, "AsyncClient",
        lambda timeout=None: FakeAsyncClient(fake_response, requests),
    )

    response = asyncio.run(main.proxy_epic_callback(code="bad-code", state="state-abc"))

    assert response.status_code == 502
