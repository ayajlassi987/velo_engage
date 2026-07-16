import logging

import httpx
from ve_connect.auth import epic_settings, get_valid_token

logger = logging.getLogger(__name__)


def _headers() -> dict:
    return {"Authorization": f"Bearer {get_valid_token()}", "Accept": "application/fhir+json"}


def _raise_with_body(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        logger.error("Epic FHIR request rejected: url=%s status=%s body=%s", resp.request.url, resp.status_code, resp.text)
    resp.raise_for_status()


def get_resource(resource_type: str, resource_id: str) -> dict:
    fhir_base = epic_settings().fhir_base.rstrip("/")
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(f"{fhir_base}/{resource_type}/{resource_id}", headers=_headers())
        _raise_with_body(resp)
        return resp.json()


def search_resources(resource_type: str, params: dict) -> list[dict]:
    """Fetches all pages of a FHIR search Bundle automatically."""
    url = f"{epic_settings().fhir_base.rstrip('/')}/{resource_type}"
    entries, first = [], True

    with httpx.Client(timeout=30.0) as client:
        while url:
            resp = client.get(url, headers=_headers(), params=params if first else {})
            _raise_with_body(resp)
            bundle = resp.json()
            first = False
            for entry in bundle.get("entry", []):
                entries.append(entry.get("resource", {}))
            url = next((l["url"] for l in bundle.get("link",[]) if l.get("relation")=="next"), None)

    return entries
