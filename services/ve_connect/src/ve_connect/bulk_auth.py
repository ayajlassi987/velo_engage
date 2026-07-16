"""
SMART Backend Services (JWT client-assertion) auth — used only for Bulk Data
$export, which Epic restricts to a separate Backend Services app
registration from the standalone-launch app auth.py talks to (see
PROJECT_STATUS.md §3.20/3.21). Genuinely different flow: no user login, no
refresh_token — every token request signs a fresh, short-lived JWT with this
app's private key and trades it for an access token via the
client_credentials grant.
"""

import base64, json, logging, os, sys, time, uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger(__name__)

for _candidate in (
    Path(__file__).resolve().parents[4] if len(Path(__file__).resolve().parents) > 4 else None,
    Path("/app"),
):
    if _candidate and (_candidate / "libs").is_dir():
        sys.path.insert(0, str(_candidate))
        break
from libs.ve_clients.vault_client import get_secret


@dataclass(frozen=True)
class BulkSettings:
    client_id: str
    token_url: str
    group_id: str
    kid: str
    private_key_pem: bytes
    fhir_base: str


def bulk_settings() -> BulkSettings:
    client_id = get_secret("epic_bulk", "client_id", "EPIC_BULK_CLIENT_ID")
    token_url = get_secret("epic_bulk", "token_url", "EPIC_BULK_TOKEN_URL")
    group_id = get_secret("epic_bulk", "group_id", "EPIC_BULK_GROUP_ID")
    kid = get_secret("epic_bulk", "kid", "EPIC_BULK_KID")
    private_key_b64 = get_secret("epic_bulk", "private_key_b64", "EPIC_BULK_PRIVATE_KEY_B64")
    fhir_base = os.getenv("EPIC_FHIR_BASE", "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/")

    missing = [name for name, val in {
        "EPIC_BULK_CLIENT_ID": client_id,
        "EPIC_BULK_TOKEN_URL": token_url,
        "EPIC_BULK_GROUP_ID": group_id,
        "EPIC_BULK_KID": kid,
        "EPIC_BULK_PRIVATE_KEY_B64": private_key_b64,
    }.items() if not val]
    if missing:
        raise RuntimeError(f"Epic Bulk Backend Services config incomplete, missing: {missing}")

    return BulkSettings(
        client_id=client_id, token_url=token_url, group_id=group_id, kid=kid,
        private_key_pem=base64.b64decode(private_key_b64), fhir_base=fhir_base,
    )


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _build_client_assertion(settings: BulkSettings) -> str:
    header = {"alg": "RS384", "typ": "JWT", "kid": settings.kid}
    now = int(time.time())
    payload = {
        "iss": settings.client_id,
        "sub": settings.client_id,
        "aud": settings.token_url,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "nbf": now,
        "exp": now + 300,
    }
    signing_input = (
        f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    )
    private_key = serialization.load_pem_private_key(settings.private_key_pem, password=None)
    signature = private_key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA384())
    return f"{signing_input}.{_b64url(signature)}"


_token_cache: dict = {"access_token": None, "expires_at": 0}


def get_bulk_token() -> str:
    """Cached access token; requests a fresh one (new JWT assertion each
    time — Epic doesn't accept a reused assertion) once within 60s of expiry."""
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    settings = bulk_settings()
    assertion = _build_client_assertion(settings)
    payload = {
        "grant_type": "client_credentials",
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": assertion,
    }
    resp = httpx.post(
        settings.token_url, data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15.0,
    )
    if resp.status_code >= 400:
        logger.error("Epic bulk token request rejected: status=%s body=%s", resp.status_code, resp.text)
    resp.raise_for_status()
    token_data = resp.json()
    _token_cache["access_token"] = token_data["access_token"]
    _token_cache["expires_at"] = time.time() + int(token_data.get("expires_in", 300))
    return _token_cache["access_token"]
