"""
SMART on FHIR Standalone Launch — OAuth2 authorization code flow with PKCE.

Step 1 (GET /auth/login):    redirect staff member to Epic login page
Step 2 (GET /auth/callback): Epic redirects back with ?code=...
Step 3:                      exchange code for access + refresh tokens
Step 4:                      store tokens in Postgres for nightly pipeline use
"""

import logging, os, secrets, hashlib, base64, sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
import psycopg2
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

for _candidate in (
    Path(__file__).resolve().parents[4] if len(Path(__file__).resolve().parents) > 4 else None,
    Path("/app"),
):
    if _candidate and (_candidate / "libs").is_dir():
        sys.path.insert(0, str(_candidate))
        break
from libs.ve_clients.vault_client import get_secret

router = APIRouter()
_state_store: dict[str, str] = {}   # state → code_verifier


@dataclass(frozen=True)
class EpicSettings:
    client_id: str
    redirect_uri: str
    scopes: str
    fhir_base: str
    auth_url: str | None
    token_url: str | None
    client_secret: str | None


def _epic_client_id() -> str | None:
    return get_secret("epic", "client_id", "EPIC_CLIENT_ID")


def _epic_client_secret() -> str | None:
    return get_secret("epic", "client_secret", "EPIC_CLIENT_SECRET")


def epic_configuration_status() -> dict:
    values = {
        "client_id": _epic_client_id(),
        "redirect_uri": os.getenv("EPIC_REDIRECT_URI"),
        "scopes": os.getenv("EPIC_SCOPES"),
        "fhir_base": os.getenv("EPIC_FHIR_BASE"),
    }
    missing = [
        env_name
        for key, env_name in {
            "client_id": "EPIC_CLIENT_ID",
            "redirect_uri": "EPIC_REDIRECT_URI",
            "scopes": "EPIC_SCOPES",
            "fhir_base": "EPIC_FHIR_BASE",
        }.items()
        if not values[key]
    ]
    return {
        "configured": not missing,
        "missing": missing,
        "fhir_base": values["fhir_base"],
        "redirect_uri": values["redirect_uri"],
        "auth_url_source": "environment" if os.getenv("EPIC_AUTH_URL") else "SMART discovery",
        "token_url_source": "environment" if os.getenv("EPIC_TOKEN_URL") else "SMART discovery",
        "client_secret_configured": bool(_epic_client_secret()),
    }


def epic_settings() -> EpicSettings:
    status = epic_configuration_status()
    values = {
        "client_id": _epic_client_id(),
        "redirect_uri": os.getenv("EPIC_REDIRECT_URI"),
        "scopes": os.getenv("EPIC_SCOPES"),
        "fhir_base": os.getenv("EPIC_FHIR_BASE"),
    }
    missing = status["missing"]
    if missing:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Epic SMART configuration is incomplete",
                "missing": missing,
                "setup": "Create services/ve_connect/.env from .env.example",
            },
        )
    return EpicSettings(
        **values,
        auth_url=os.getenv("EPIC_AUTH_URL"),
        token_url=os.getenv("EPIC_TOKEN_URL"),
        client_secret=_epic_client_secret(),
    )


@router.get("/auth/config")
async def config_status():
    """Report non-secret SMART configuration readiness."""
    return epic_configuration_status()


async def _smart_endpoints(settings: EpicSettings) -> tuple[str, str]:
    if settings.auth_url and settings.token_url:
        return settings.auth_url, settings.token_url
    discovery_url = (
        f"{settings.fhir_base.rstrip('/')}/.well-known/smart-configuration"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(discovery_url)
            response.raise_for_status()
            discovery = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Unable to discover Epic SMART OAuth endpoints",
                "discovery_url": discovery_url,
                "hint": "Set EPIC_AUTH_URL and EPIC_TOKEN_URL explicitly",
            },
        ) from exc
    auth_url = settings.auth_url or discovery.get("authorization_endpoint")
    token_url = settings.token_url or discovery.get("token_endpoint")
    if not auth_url or not token_url:
        raise HTTPException(
            status_code=502,
            detail="Epic SMART discovery did not return authorization and token endpoints",
        )
    return auth_url, token_url


def _db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST","localhost"), port=int(os.getenv("DB_PORT",5432)),
        dbname=os.getenv("DB_NAME","velodb"), user=get_secret("postgres", "user", "DB_USER") or "velo",
        password=get_secret("postgres", "password", "DB_PASSWORD") or "velo_secret",
    )


def _pkce_pair() -> tuple[str, str]:
    """PKCE S256 — Epic requires this for confidential apps."""
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


@router.get("/auth/login")
async def login():
    """Redirect staff member to Epic login. They authenticate with Epic, not with your app."""
    settings = epic_settings()
    auth_url, _ = await _smart_endpoints(settings)
    state = secrets.token_urlsafe(16)
    verifier, challenge = _pkce_pair()
    _state_store[state] = verifier

    params = {
        "response_type": "code",
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "scope": settings.scopes,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "aud": settings.fhir_base,
    }
    return RedirectResponse(f"{auth_url}?{urlencode(params)}")


@router.get("/auth/callback")
@router.get("/")
async def callback(code: str, state: str):
    """Epic redirects here after the staff member approves. Exchange code for tokens.

    Registered at both /auth/callback and the bare root path: the app's
    registered Epic redirect URI is the bare ngrok domain with no path, so
    this must also answer at "/" for the exact-match redirect_uri Epic
    requires.
    """
    verifier = _state_store.pop(state, None)
    if not verifier:
        return {"error": "invalid_state — restart login at /auth/login"}

    settings = epic_settings()
    _, token_url = await _smart_endpoints(settings)
    token_payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.redirect_uri,
        "client_id": settings.client_id,
        "code_verifier": verifier,
    }
    if settings.client_secret:
        token_payload["client_secret"] = settings.client_secret

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            token_url,
            data=token_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        # Log the full rejection before raising — Epic's error body (error +
        # error_description) is the only way to tell which of the guide's
        # ranked causes this actually is; a bare raise_for_status() discards
        # exactly the information needed to diagnose it.
        if resp.status_code >= 400:
            logger.error(
                "Epic token exchange rejected: status=%s body=%s request=%s",
                resp.status_code,
                resp.text,
                {k: v for k, v in token_payload.items() if k not in ("client_secret", "code_verifier")},
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Epic rejected the token exchange",
                    "epic_status": resp.status_code,
                    "epic_response": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text,
                },
            )
        token_data = resp.json()

    _store_tokens(token_data)
    return {
        "status": "authorized",
        "expires_in": token_data.get("expires_in"),
        "message": "Velo Connect authorized. The nightly pipeline will use these credentials automatically.",
    }


def _store_tokens(token_data: dict):
    clinic_id = os.getenv("CLINIC_ID", "clinic_alnoor_001")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(token_data.get("expires_in", 3600)))
    conn = _db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO epic_tokens (clinic_id, access_token, refresh_token, expires_at, scope, id_token)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (clinic_id) DO UPDATE SET
          access_token=EXCLUDED.access_token, refresh_token=EXCLUDED.refresh_token,
          expires_at=EXCLUDED.expires_at, scope=EXCLUDED.scope,
          id_token=EXCLUDED.id_token, updated_at=now()
    """, (clinic_id, token_data["access_token"], token_data.get("refresh_token"),
          expires_at, token_data.get("scope"), token_data.get("id_token")))
    conn.commit(); cur.close(); conn.close()


def get_valid_token() -> str:
    """Returns a valid access token, refreshing silently if expired. Called before every FHIR call."""
    clinic_id = os.getenv("CLINIC_ID", "clinic_alnoor_001")
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT access_token, refresh_token, expires_at FROM epic_tokens WHERE clinic_id=%s", (clinic_id,))
    row = cur.fetchone(); cur.close(); conn.close()

    if not row:
        raise RuntimeError("No Epic token. Visit http://localhost:8003/auth/login to authorize.")

    access_token, refresh_token, expires_at = row
    if datetime.now(timezone.utc) >= expires_at - timedelta(minutes=5):
        if not refresh_token:
            raise RuntimeError("Token expired — re-authorize at /auth/login")
        return _refresh(refresh_token)
    return access_token


def _refresh(refresh_token: str) -> str:
    settings = epic_settings()
    token_url = settings.token_url
    if not token_url:
        discovery_url = (
            f"{settings.fhir_base.rstrip('/')}/.well-known/smart-configuration"
        )
        response = httpx.get(discovery_url, timeout=15.0)
        response.raise_for_status()
        token_url = response.json().get("token_endpoint")
    if not token_url:
        raise RuntimeError("Epic SMART token endpoint is not configured or discoverable")
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": settings.client_id,
    }
    if settings.client_secret:
        payload["client_secret"] = settings.client_secret
    resp = httpx.post(
        token_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if resp.status_code >= 400:
        logger.error("Epic token refresh rejected: status=%s body=%s", resp.status_code, resp.text)
    resp.raise_for_status()
    token_data = resp.json()
    _store_tokens(token_data)
    return token_data["access_token"]
