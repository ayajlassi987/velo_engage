"""Pure templating/formatting logic in ve_reach/sender.py — no network calls
(send_template/send_text/dispatch_campaign hit Meta's API and are covered by
Phase 4c's mocked-boundary tests instead). Uses the real policies/opportunities
YAML files already in the repo rather than mocking policy_for_family, since
policy_catalog.py reads them directly and they're genuine fixtures, not
just illustrative examples."""

import os

from ve_reach.sender import (
    TemplateMessage,
    _body_parameters,
    _delivery_context,
    _parameter_value,
    build_campaign_message,
    build_campaign_text,
)


def test_body_parameters_wraps_values_as_text_components():
    result = _body_parameters("Camila", "Al Noor Clinic")
    assert result == [{
        "type": "body",
        "parameters": [
            {"type": "text", "text": "Camila"},
            {"type": "text", "text": "Al Noor Clinic"},
        ],
    }]


def test_delivery_context_includes_patient_and_clinic_name(monkeypatch):
    monkeypatch.setenv("CLINIC_NAME", "Al Noor Clinic")
    context = _delivery_context({"rule_evidence": {"days_since_last_visit": 45}}, "Camila")
    assert context["patient_name"] == "Camila"
    assert context["clinic_name"] == "Al Noor Clinic"
    assert context["days_since_last_visit"] == 45


def test_parameter_value_reads_from_evidence_source():
    parameter = {"source": "evidence", "key": "days_since_last_visit", "default": 0}
    value = _parameter_value(parameter, context={}, evidence={"days_since_last_visit": 90})
    assert value == 90


def test_parameter_value_falls_back_to_default_when_missing():
    parameter = {"source": "evidence", "key": "missing_key", "default": "n/a"}
    value = _parameter_value(parameter, context={}, evidence={})
    assert value == "n/a"


def test_parameter_value_reads_from_context_source():
    parameter = {"source": "patient_name"}
    value = _parameter_value(parameter, context={"patient_name": "Camila"}, evidence={})
    assert value == "Camila"


def test_build_campaign_text_family_c_real_policy(monkeypatch):
    monkeypatch.setenv("CLINIC_NAME", "Al Noor Clinic")
    campaign = {"family": "C", "rule_evidence": {}}
    text = build_campaign_text(campaign, "Camila")
    assert "Camila" in text
    assert "Al Noor Clinic" in text
    assert "open treatment plan" in text.lower()


def test_build_campaign_message_family_c_real_policy(monkeypatch):
    monkeypatch.setenv("CLINIC_NAME", "Al Noor Clinic")
    campaign = {"family": "C", "rule_evidence": {}}
    message = build_campaign_message(campaign, "Camila")
    assert isinstance(message, TemplateMessage)
    assert message.name == "velo_treatment_followup_en_v1"
    assert message.language_code == "en_US"
    params = message.components[0]["parameters"]
    assert params[0]["text"] == "Camila"
    assert params[1]["text"] == "Al Noor Clinic"


def test_build_campaign_message_respects_env_template_override(monkeypatch):
    monkeypatch.setenv("CLINIC_NAME", "Al Noor Clinic")
    monkeypatch.setenv("WHATSAPP_TEMPLATE_FAMILY_C", "custom_template_v2")
    campaign = {"family": "C", "rule_evidence": {}}
    message = build_campaign_message(campaign, "Camila")
    assert message.name == "custom_template_v2"
