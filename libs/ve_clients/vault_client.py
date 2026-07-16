"""Shared Vault client — every service that needs a credential goes through
this instead of reading it straight from an environment variable.

Uses stdlib `urllib.request` rather than the `hvac` package: Vault's KV v2
read is a single GET with a token header, not worth a new dependency in
every service for.

Never a hard dependency on Vault being reachable — mirrors this project's
established pattern for optional infra (Redis feature cache, Neo4j clinical
graph): if Vault is unreachable, unsealed differently than expected, or the
path doesn't exist, callers fall back to `os.environ`. A clinic's outreach
pipeline should not go down because the secrets backend hiccuped; it should
carry on with whatever was in its environment at container start.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from functools import lru_cache

logger = logging.getLogger(__name__)

VAULT_ADDR = os.getenv("VAULT_ADDR", "http://vault:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN")


@lru_cache(maxsize=32)
def _read_secret(path: str) -> dict | None:
    """One Vault read per (path, process) — secrets are read once at
    service startup, not per-request, so a short-lived Vault outage after
    boot never affects an already-running service."""
    if not VAULT_TOKEN:
        return None
    url = f"{VAULT_ADDR}/v1/secret/data/{path}"
    req = urllib.request.Request(url, headers={"X-Vault-Token": VAULT_TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = json.loads(resp.read())
            return body["data"]["data"]
    except (urllib.error.URLError, KeyError, TimeoutError, ValueError) as exc:
        logger.warning("Vault read failed for secret/%s (%s) — falling back to environment", path, exc)
        return None


def get_secret(path: str, key: str, env_fallback: str) -> str | None:
    """Reads `key` from Vault secret at `secret/<path>`, falling back to
    `os.environ[env_fallback]` if Vault is unreachable or the key/path is
    missing there."""
    secret = _read_secret(path)
    if secret is not None and key in secret:
        return secret[key]
    return os.getenv(env_fallback)
