import os
import sys
import httpx
from dataclasses import dataclass
from typing import Optional
import logging

from ve_reach.policy_catalog import policy_for_family

sys.path.insert(0, ".")
from libs.ve_clients.vault_client import get_secret  # noqa: E402

logger = logging.getLogger(__name__)
GRAPH_API_BASE = "https://graph.facebook.com"


@dataclass(frozen=True)
class TemplateMessage:
    name: str
    language_code: str
    components: list[dict]


def _headers() -> dict:
    token = get_secret("whatsapp", "access_token", "WHATSAPP_ACCESS_TOKEN")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _url() -> str:
    phone_number_id = get_secret("whatsapp", "phone_number_id", "WHATSAPP_PHONE_NUMBER_ID")
    return f"{GRAPH_API_BASE}/{os.getenv('WHATSAPP_API_VERSION', 'v25.0')}/{phone_number_id or ''}/messages"


def send_template(to: str, template_name: str, language_code: str = "ar",
                   components: Optional[list] = None) -> dict:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {"name": template_name, "language": {"code": language_code}},
    }
    if components:
        payload["template"]["components"] = components

    with httpx.Client(timeout=10.0) as client:
        resp = client.post(_url(), headers=_headers(), json=payload)
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Sent template '{template_name}' to {to}: {data}")
        return data


def send_text(to: str, body: str) -> dict:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(_url(), headers=_headers(), json=payload)
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Sent text to {to}: {data}")
        return data


def _body_parameters(*values: object) -> list[dict]:
    return [{
        "type": "body",
        "parameters": [{"type": "text", "text": str(value)} for value in values],
    }]


def _delivery_context(campaign: dict, patient_name: str) -> dict:
    evidence = campaign.get("rule_evidence", {})
    return {
        "patient_name": patient_name,
        "clinic_name": os.getenv("CLINIC_NAME", "Al Noor Clinic"),
        **evidence,
    }


def _parameter_value(parameter: dict, context: dict, evidence: dict) -> object:
    source = parameter.get("source")
    if source == "evidence":
        return evidence.get(parameter.get("key"), parameter.get("default", ""))
    return context.get(source, parameter.get("default", ""))


def build_campaign_text(campaign: dict, patient_name: str) -> str:
    policy = policy_for_family(campaign.get("family", ""))
    return policy["delivery"]["session_text"].format(
        **_delivery_context(campaign, patient_name)
    )


def build_campaign_message(campaign: dict, patient_name: str) -> TemplateMessage:
    family = campaign.get("family", "")
    policy = policy_for_family(family)
    template = policy["delivery"]["template"]
    evidence = campaign.get("rule_evidence", {})
    context = _delivery_context(campaign, patient_name)
    values = [
        _parameter_value(parameter, context, evidence)
        for parameter in template.get("parameters", [])
    ]
    return TemplateMessage(
        name=os.getenv(f"WHATSAPP_TEMPLATE_FAMILY_{family}", template["name"]),
        language_code=template.get(
            "language", os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US")
        ),
        components=_body_parameters(*values),
    )


def dispatch_campaign(campaign: dict, phone: str, patient_name: str) -> dict:
    message = build_campaign_message(campaign, patient_name)
    return send_template(
        to=phone,
        template_name=message.name,
        language_code=message.language_code,
        components=message.components,
    )
