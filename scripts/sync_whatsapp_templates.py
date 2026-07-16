#!/usr/bin/env python3
"""Create missing Meta WhatsApp templates from enabled family YAML policies."""

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ORCHESTRATOR_SRC = Path(__file__).parents[1] / "services" / "ve_orchestrator" / "src"
sys.path.insert(0, str(ORCHESTRATOR_SRC))

from ve_orchestrator.policy_engine import active_policies  # noqa: E402

ENV_PATH = Path(__file__).parents[1] / "services" / "ve_reach" / ".env"


def load_env_file() -> None:
    if not ENV_PATH.exists():
        return
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def graph_request(method: str, path: str, payload: dict | None = None) -> dict:
    version = os.getenv("WHATSAPP_API_VERSION", "v25.0")
    url = f"https://graph.facebook.com/{version}/{path}"
    body = json.dumps(payload).encode() if payload else None
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {os.environ['WHATSAPP_ACCESS_TOKEN']}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"Meta API HTTP {exc.code}: {detail}") from exc


def parameter_key(parameter: dict) -> str:
    if parameter["source"] == "evidence":
        return parameter["key"]
    return parameter["source"]


def parameter_example(parameter: dict) -> str:
    examples = {"patient_name": "Aya", "clinic_name": "Al Noor Clinic"}
    key = parameter_key(parameter)
    return str(examples.get(key, parameter.get("default", "30")))


def template_payload(policy: dict) -> dict:
    template = policy["delivery"]["template"]
    body = policy["delivery"]["session_text"]
    examples = []
    for index, parameter in enumerate(template.get("parameters", []), start=1):
        body = body.replace(f"{{{parameter_key(parameter)}}}", f"{{{{{index}}}}}")
        examples.append(parameter_example(parameter))
    component = {"type": "BODY", "text": body}
    if examples:
        component["example"] = {"body_text": [examples]}
    return {
        "name": template["name"],
        "language": template.get("language", "en_US"),
        "category": template.get("category", "MARKETING"),
        "components": [component],
    }


def main() -> None:
    load_env_file()
    required = ["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_BUSINESS_ACCOUNT_ID"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing environment values: {', '.join(missing)}")

    account_id = os.environ["WHATSAPP_BUSINESS_ACCOUNT_ID"]
    existing_response = graph_request(
        "GET", f"{account_id}/message_templates?fields=name,language,status&limit=100"
    )
    existing = {
        (item["name"], item["language"]): item["status"]
        for item in existing_response.get("data", [])
    }

    for policy in active_policies():
        payload = template_payload(policy)
        key = (payload["name"], payload["language"])
        if key in existing:
            print(f"[{policy['family']}] {payload['name']}: {existing[key]}")
            continue
        result = graph_request("POST", f"{account_id}/message_templates", payload)
        print(f"[{policy['family']}] {payload['name']}: {result.get('status', 'CREATED')}")


if __name__ == "__main__":
    main()
