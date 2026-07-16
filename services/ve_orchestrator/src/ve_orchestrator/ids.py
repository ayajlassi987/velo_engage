"""
Deterministic ID generation — replaces uuid.uuid4() so that re-running
the same logical step never creates duplicate rows.

An opportunity is uniquely identified by (patient_id, clinic_id, rule_name,
the date it was evaluated) — same patient, same rule, same day → same ID,
so ON CONFLICT actually catches it on retry.
"""

import hashlib
from datetime import date


def deterministic_opportunity_id(patient_id: str, clinic_id: str, rule_name: str, as_of: date) -> str:
    raw = f"opp:{patient_id}:{clinic_id}:{rule_name}:{as_of.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def deterministic_campaign_id(opportunity_id: str, as_of: date) -> str:
    raw = f"campaign:{opportunity_id}:{as_of.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]