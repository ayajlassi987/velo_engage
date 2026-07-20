"""Client for NVIDIA's NemoGuard content-safety NIM
(llama-3.1-nemoguard-8b-content-safety).

Prompt format and output schema confirmed against NVIDIA's own published
API example for this exact model (docs.api.nvidia.com), after live testing
on the DGX showed a custom ad-hoc category list produces unreliable
verdicts (the model is fine-tuned on this specific 23-category taxonomy
and JSON output format, not arbitrary categories fed to it at inference
time).

Deliberately fail-safe: any error (unreachable, unexpected response shape,
timeout) returns False (block) rather than True. A safety gate that fails
open on error defeats its own purpose.
"""

import json
import logging
import os

import httpx

NEMOGUARD_URL = os.getenv("NEMOGUARD_URL", "http://localhost:8001")

logger = logging.getLogger(__name__)

SAFETY_CHECK_PROMPT = """Task: Check if there is unsafe content in the user or agent messages in the below conversation in accordance with our safety policy with the below categories. Provide a safe or unsafe rating for both the user message and the agent response. If there is unsafe content, please also provide a list of violated categories according to our safety policy below.
<BEGIN UNSAFE CONTENT CATEGORIES>
S1: Violence.
S2: Sexual.
S3: Criminal Planning/Confessions.
S4: Guns and Illegal Weapons.
S5: Controlled/Regulated Substances.
S6: Suicide and Self Harm.
S7: Sexual (minor).
S8: Hate/Identity Hate.
S9: PII/Privacy.
S10: Harassment.
S11: Threat.
S12: Profanity.
S13: Needs Caution.
S14: Other.
S15: Manipulation.
S16: Fraud/Deception.
S17: Malware.
S18: High Risk Gov Decision Making.
S19: Political/Misinformation/Conspiracy.
S20: Copyright/Trademark/Plagiarism.
S21: Unauthorized Advice.
S22: Illegal Activity.
S23: Immoral/Unethical.
<END UNSAFE CONTENT CATEGORIES>
<BEGIN CONVERSATION>
user: {text}
<END CONVERSATION>
Provide your safety assessment in JSON format: {{"User Safety": safe or unsafe, "Safety Categories": comma-separated list if unsafe}}. Output only JSON."""


# "Unauthorized Advice" (S21) fires on ordinary treatment/medication
# language ("recommend ibuprofen 400mg") because the category is designed
# to stop a chatbot giving unlicensed advice to an end user — the wrong
# lens for a doctor's own note. Confirmed live against the real NIM: a
# neutral note passed clean, an identical note with dosing language
# tripped only this category. Excluded from blocking per user decision;
# every other category (violence, self-harm, PII, illegal activity, etc.)
# still blocks normally.
_NON_BLOCKING_CATEGORIES = {"unauthorized advice"}


def _is_safe_verdict(response_text: str) -> bool:
    """Parses the NIM's JSON verdict per NVIDIA's documented output schema
    ({"User Safety": "safe"|"unsafe", "Safety Categories": "..."}). An
    explicit "safe" passes; "unsafe" also passes if every listed category
    is in _NON_BLOCKING_CATEGORIES. Any parse failure, unexpected shape, or
    "unsafe" with no parseable category list blocks (fail-safe)."""
    try:
        data = json.loads(response_text.strip())
    except (json.JSONDecodeError, AttributeError):
        logger.warning(f"NemoGuard response was not valid JSON, blocking: {response_text[:200]!r}")
        return False
    user_safety = str(data.get("User Safety", "")).strip().lower()
    if user_safety == "safe":
        return True
    if user_safety != "unsafe":
        logger.warning(f"NemoGuard returned unexpected User Safety value, blocking: {response_text[:200]!r}")
        return False
    categories = [c.strip().lower() for c in str(data.get("Safety Categories", "")).split(",") if c.strip()]
    if categories and all(c in _NON_BLOCKING_CATEGORIES for c in categories):
        logger.info(f"NemoGuard flagged only non-blocking categories {categories}, passing: {response_text[:200]!r}")
        return True
    return False


def check_safety(text: str) -> bool:
    """Returns True only if NemoGuard explicitly confirms the text is safe.
    Any communication or parsing failure blocks (returns False) rather
    than silently passing unchecked content to MedGemma."""
    payload = {
        "messages": [{"role": "user", "content": SAFETY_CHECK_PROMPT.format(text=text)}],
        "max_tokens": 100,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{NEMOGUARD_URL}/v1/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        return _is_safe_verdict(content)
    except Exception as exc:
        logger.warning(f"NemoGuard check failed ({exc}) — blocking (fail-safe, not fail-open)")
        return False


def health_check() -> dict:
    with httpx.Client(timeout=10.0) as client:
        response = client.get(f"{NEMOGUARD_URL}/v1/health/ready")
        response.raise_for_status()
        return {"status": "ready"} if response.status_code == 200 else response.json()
