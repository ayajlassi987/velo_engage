"""Non-LLM sanity checks on MedGemma's structured extraction output.

This is the actual hallucination-mitigation mechanism for this task — not
NemoGuard, which checks content *safety* (toxicity), not factual accuracy
of a medical extraction (see nemoguard_client.py's own docstring). These
checks can't verify an extracted diagnosis is *true*, but they can catch
the cheap, common failure modes: malformed output, empty-but-required
fields, and diagnosis codes that don't even look like real codes.

Every check appends a human-readable string to `flags` rather than
silently dropping data — a clinician reviewing the console should see
exactly what wasn't verified, not have it disappear.
"""

import re

ICD10_PATTERN = re.compile(r"^[A-TV-Z][0-9][0-9AB](\.[0-9A-TV-Z]{1,4})?$", re.IGNORECASE)

REQUIRED_KEYS = ("diagnoses", "medications", "procedures", "follow_up_recommendations", "clinical_risks")


def validate(extraction: dict) -> tuple[dict, list[str]]:
    """Returns (cleaned_extraction, flags). Never raises — a validation
    failure is recorded as a flag, not an exception that would drop the
    whole extraction."""
    flags: list[str] = []
    cleaned: dict = {}

    for key in REQUIRED_KEYS:
        value = extraction.get(key)
        if value is None:
            flags.append(f"'{key}' missing from MedGemma response — defaulted to empty list")
            cleaned[key] = []
        elif not isinstance(value, list):
            flags.append(f"'{key}' was not a list ({type(value).__name__}) — defaulted to empty list")
            cleaned[key] = []
        else:
            cleaned[key] = [str(item) for item in value if item]

    for key in extraction:
        if key not in REQUIRED_KEYS:
            flags.append(f"Unexpected extra key in MedGemma response: '{key}' (ignored)")

    empty_medication_names = [m for m in cleaned["medications"] if not m.strip()]
    if empty_medication_names:
        flags.append(f"{len(empty_medication_names)} empty medication name(s) removed")
        cleaned["medications"] = [m for m in cleaned["medications"] if m.strip()]

    # Diagnoses aren't required to be bare ICD-10 codes (MedGemma may
    # extract a descriptive diagnosis name instead), so this doesn't
    # reject non-code-shaped diagnoses — it only flags them for a human
    # to notice they weren't in a verifiable code format.
    for diagnosis in cleaned["diagnoses"]:
        code_candidate = diagnosis.split()[0] if diagnosis.split() else ""
        if not ICD10_PATTERN.match(code_candidate):
            flags.append(f"Diagnosis '{diagnosis}' does not start with a recognizable ICD-10-shaped code")

    return cleaned, flags
