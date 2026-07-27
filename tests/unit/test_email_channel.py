"""ve_reach.channels.email's SendGrid call — mocked at the httpx.Client
boundary (same pattern as test_sender_http.py), no real network call."""

import httpx
import pytest

import ve_reach.channels.email as email_channel


class FakeResponse:
    def __init__(self, status_code=202, message_id="msg_123"):
        self.status_code = status_code
        self.headers = {"X-Message-Id": message_id}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


class FakeClient:
    def __init__(self, timeout=None):
        self.requests = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, headers=None, json=None):
        self.requests.append({"url": url, "headers": headers, "json": json})
        return FakeResponse()


def test_send_email_posts_correct_payload_shape(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "test_key")
    monkeypatch.setenv("EMAIL_FROM_ADDRESS", "clinic@example.com")
    fake_client = FakeClient()
    monkeypatch.setattr(httpx, "Client", lambda timeout=None: fake_client)

    result = email_channel.send_email("patient@example.com", "Reminder", "Please book")

    assert result == {"status": "accepted", "message_id": "msg_123"}
    sent = fake_client.requests[0]
    assert sent["url"] == "https://api.sendgrid.com/v3/mail/send"
    assert sent["headers"]["Authorization"] == "Bearer test_key"
    assert sent["json"]["personalizations"][0]["to"][0]["email"] == "patient@example.com"
    assert sent["json"]["from"]["email"] == "clinic@example.com"
    assert sent["json"]["subject"] == "Reminder"
    assert sent["json"]["content"][0]["value"] == "Please book"


def test_send_email_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.delenv("EMAIL_FROM_ADDRESS", raising=False)

    with pytest.raises(RuntimeError, match="SendGrid is not configured"):
        email_channel.send_email("patient@example.com", "Reminder", "Please book")


def test_send_email_raises_on_http_error(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "test_key")
    monkeypatch.setenv("EMAIL_FROM_ADDRESS", "clinic@example.com")

    class FailingClient(FakeClient):
        def post(self, url, headers=None, json=None):
            return FakeResponse(status_code=400)

    monkeypatch.setattr(httpx, "Client", lambda timeout=None: FailingClient())

    with pytest.raises(httpx.HTTPStatusError):
        email_channel.send_email("patient@example.com", "Reminder", "Please book")
