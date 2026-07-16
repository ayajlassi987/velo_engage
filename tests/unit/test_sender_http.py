"""ve_reach/sender.py's actual HTTP calls (send_template/send_text) —
mocked at the httpx.Client boundary, no real network call to Meta's Graph
API. Complements test_sender.py's pure-templating tests."""

import httpx

import ve_reach.sender as sender


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._json


class FakeClient:
    def __init__(self, timeout=None):
        self.requests = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, headers=None, json=None):
        self.requests.append({"url": url, "headers": headers, "json": json})
        return FakeResponse({"messages": [{"id": "wamid.test123"}]})


def test_send_template_posts_correct_payload_shape(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test_token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123456")

    fake_client_holder = {}

    def fake_client_factory(timeout=None):
        client = FakeClient(timeout)
        fake_client_holder["client"] = client
        return client

    monkeypatch.setattr(sender.httpx, "Client", fake_client_factory)

    result = sender.send_template(
        to="+971500000000", template_name="velo_treatment_followup_en_v1",
        language_code="en_US", components=[{"type": "body", "parameters": []}],
    )

    assert result == {"messages": [{"id": "wamid.test123"}]}
    request = fake_client_holder["client"].requests[0]
    assert request["json"]["messaging_product"] == "whatsapp"
    assert request["json"]["to"] == "+971500000000"
    assert request["json"]["type"] == "template"
    assert request["json"]["template"]["name"] == "velo_treatment_followup_en_v1"
    assert request["json"]["template"]["language"]["code"] == "en_US"
    assert request["headers"]["Authorization"] == "Bearer test_token"


def test_send_template_omits_components_when_none_given(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test_token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123456")

    fake_client_holder = {}
    monkeypatch.setattr(sender.httpx, "Client", lambda timeout=None: fake_client_holder.setdefault("client", FakeClient()))

    sender.send_template(to="+971500000000", template_name="tmpl_x")

    request = fake_client_holder["client"].requests[0]
    assert "components" not in request["json"]["template"]


def test_send_text_posts_correct_payload_shape(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test_token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123456")

    fake_client_holder = {}
    monkeypatch.setattr(sender.httpx, "Client", lambda timeout=None: fake_client_holder.setdefault("client", FakeClient()))

    sender.send_text(to="+971500000000", body="Reply STOP to opt out.")

    request = fake_client_holder["client"].requests[0]
    assert request["json"]["type"] == "text"
    assert request["json"]["text"]["body"] == "Reply STOP to opt out."
