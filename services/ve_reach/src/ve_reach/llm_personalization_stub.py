"""STUB — MedGemma + NemoGuard LLM personalization layer. NOT FUNCTIONAL.

The master spec calls for optional low-stakes copy personalization via a
GPU-hosted MedGemma 27B (vLLM), safety-gated by a NemoGuard NIM before any
send. Neither is provisioned in this environment (no GPU node, no vLLM/NIM
endpoints configured), so this module only documents the intended interface.

Template-first policy is enforced today regardless of this stub: regulated
and clinical messages are ALWAYS sent from the pre-approved WhatsApp
templates in policies/opportunities/*.yml (see ve_reach.sender), never
LLM-generated. This module would only ever apply to optional cosmetic copy
variation on top of an already-approved template — never to clinical
content or consent/opt-out handling.

To make this real:
  1. Stand up a vLLM instance serving MedGemma 27B and a NemoGuard NIM,
     expose both as internal HTTP endpoints.
  2. Replace personalize() with a real call to the vLLM endpoint.
  3. Replace safety_check() with a real call to the NemoGuard NIM; a send
     must be blocked (not just logged) if this returns False.
"""

STATUS = "stub"  # not wired into any live code path


def personalize(template_text: str, patient_context: dict) -> str:
    """Returns the template text unchanged — no LLM call is made."""
    return template_text


def safety_check(text: str) -> bool:
    """Stub content-safety gate. Always returns True (does not block).
    Do not enable LLM-generated copy in production until this calls a real
    NemoGuard (or equivalent) content-safety service."""
    return True
