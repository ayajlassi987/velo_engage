"""Keycloak OIDC login for the console — owner vs. staff role gating.

Deliberately hand-rolled instead of pulling in authlib: only two HTTP calls
are needed (token exchange, JWKS fetch-for-verification), both via stdlib
urllib, plus PyJWT for signature verification. Two issuer URLs matter here:
KEYCLOAK_ISSUER (external, http://localhost:8081/...) is what the browser is
redirected to and what ends up in the token's `iss` claim (forced via the
realm's `frontendUrl` attribute — see infra/keycloak/velo-engage-realm.json).
KEYCLOAK_ISSUER_INTERNAL (http://keycloak:8080/...) is what this container
uses to reach Keycloak directly over the Docker network for the token
exchange and JWKS fetch — "localhost" from inside this container would not
reach the keycloak container.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.error import HTTPError

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from jwt import PyJWKClient

# libs/ is copied in alongside src/ (see Dockerfile) — same candidate-path
# pattern main.py uses for ml/registry, so this module works whether it's
# running from the repo checkout (local dev) or the Docker image.
for _candidate in (Path(__file__).resolve().parents[4], Path("/app")):
    if _candidate and (_candidate / "libs").is_dir():
        sys.path.insert(0, str(_candidate))
        break
from libs.ve_clients.vault_client import get_secret

ISSUER = os.getenv("KEYCLOAK_ISSUER", "http://localhost:8081/realms/velo-engage")
ISSUER_INTERNAL = os.getenv("KEYCLOAK_ISSUER_INTERNAL", "http://keycloak:8080/realms/velo-engage")
CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "ve-console")
CLIENT_SECRET = get_secret("keycloak", "client_secret", "KEYCLOAK_CLIENT_SECRET") or ""
REDIRECT_URI = os.getenv("KEYCLOAK_REDIRECT_URI", "http://localhost:8002/auth/callback")
CLINIC_NAME = os.getenv("CLINIC_NAME", "Al Noor Clinic")
CONSOLE_BASE_URL = os.getenv("CONSOLE_BASE_URL", "http://localhost:8002")

_jwks_client = PyJWKClient(f"{ISSUER_INTERNAL}/protocol/openid-connect/certs")
_templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# Paths that must stay reachable without a session, or login/logout would
# themselves get redirected back into /login forever.
PUBLIC_PATHS = {"/login", "/auth/callback", "/health"}

router = APIRouter()


def _token_endpoint() -> str:
    return f"{ISSUER_INTERNAL}/protocol/openid-connect/token"


def _authorize_url(state: str) -> str:
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid",
        "state": state,
    }
    return f"{ISSUER}/protocol/openid-connect/auth?{urllib.parse.urlencode(params)}"


def _exchange_code(code: str) -> dict:
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }).encode()
    req = urllib.request.Request(_token_endpoint(), data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Keycloak token exchange failed: {exc.read()}") from exc


def _decode_id_token(id_token: str) -> dict:
    signing_key = _jwks_client.get_signing_key_from_jwt(id_token)
    return jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=CLIENT_ID,
        issuer=ISSUER,
    )


def current_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# Hierarchical, not flat: admin can do everything owner can, owner can do
# everything staff can. Enforced by checking for *either* role that grants
# the tier, not by a separate "admin implies owner" role-expansion step —
# simpler to reason about with only three tiers.
def require_owner(user: dict = Depends(current_user)) -> dict:
    if not {"owner", "admin"} & set(user.get("roles", [])):
        raise HTTPException(status_code=403, detail="Owner access required for this page")
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if "admin" not in user.get("roles", []):
        raise HTTPException(status_code=403, detail="Admin access required for this page")
    return user


@router.get("/login", include_in_schema=False)
def login(request: Request, next: str = "/overview", logged_out: bool = False, error: str = ""):
    if request.session.get("user") and not logged_out:
        return RedirectResponse(next)
    next_path = next if next.startswith("/") else "/overview"
    request.session["post_login_redirect"] = next_path
    return _templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "clinic_name": CLINIC_NAME,
            "authorize_url": _authorize_url(state=next_path),
            "logged_out": logged_out,
            "error": error,
        },
    )


@router.get("/auth/callback", include_in_schema=False)
def auth_callback(request: Request, code: str = "", error: str = ""):
    if error:
        return RedirectResponse(f"/login?error={urllib.parse.quote('Sign-in was cancelled or failed. Please try again.')}")
    try:
        tokens = _exchange_code(code)
        claims = _decode_id_token(tokens["id_token"])
    except HTTPException:
        return RedirectResponse(f"/login?error={urllib.parse.quote('Sign-in could not be completed. Please try again.')}")
    roles = [r for r in claims.get("realm_access", {}).get("roles", []) if r in ("admin", "owner", "staff")]
    request.session["user"] = {
        "username": claims.get("preferred_username", "unknown"),
        "name": claims.get("name") or claims.get("preferred_username", "unknown"),
        "roles": roles,
    }
    redirect_to = request.session.pop("post_login_redirect", "/overview")
    return RedirectResponse(redirect_to)


@router.get("/logout", include_in_schema=False)
def logout(request: Request):
    request.session.clear()
    logout_url = f"{ISSUER}/protocol/openid-connect/logout?{urllib.parse.urlencode({'post_logout_redirect_uri': f'{CONSOLE_BASE_URL}/login?logged_out=1', 'client_id': CLIENT_ID})}"
    return RedirectResponse(logout_url)
