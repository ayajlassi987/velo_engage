"""VE Graph — queries the Neo4j clinical-recall knowledge graph for family B.

Recall logic lives as data in Neo4j (see scripts/seed_neo4j_clinical_graph.py),
not as code here: this module only translates a patient's condition codes/age
into a Cypher lookup and picks the most overdue recall.
"""

import os
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path

from neo4j import GraphDatabase

for _candidate in (
    Path(__file__).resolve().parents[4] if len(Path(__file__).resolve().parents) > 4 else None,
    Path("/app"),
):
    if _candidate and (_candidate / "libs").is_dir():
        sys.path.insert(0, str(_candidate))
        break
from libs.ve_clients.vault_client import get_secret

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")

CONDITION_QUERY = """
MATCH (c:Condition)-[r:REQUIRES_FOLLOWUP]->(s:Service)
WHERE c.code IN $codes
OPTIONAL MATCH (s)-[:DELIVERED_BY]->(sp:Specialty)
RETURN c.code AS condition_code, c.name AS condition_name, s.name AS service,
       r.interval_days AS interval_days, r.evidence_source AS evidence_source,
       sp.name AS specialty
"""

AGE_QUERY = """
MATCH (a:AgeBand)-[r:SCREENING_DUE]->(s:Service)
WHERE $age >= a.min_age AND $age <= a.max_age
OPTIONAL MATCH (s)-[:DELIVERED_BY]->(sp:Specialty)
RETURN NULL AS condition_code, 'age-based screening' AS condition_name,
       s.name AS service, r.interval_days AS interval_days,
       r.evidence_source AS evidence_source, sp.name AS specialty
"""

# UNWIND variants of the same two queries — one Neo4j round trip for every
# candidate patient in a run, instead of clinical_recall_due opening a new
# session and running up to 2 queries per patient (the worst-scaling piece
# of evaluate_rules; see PROJECT_STATUS.md). patient_id travels through so
# results can be grouped back per patient in Python.
CONDITION_QUERY_BATCH = """
UNWIND $patients AS patient
MATCH (c:Condition)-[r:REQUIRES_FOLLOWUP]->(s:Service)
WHERE c.code IN patient.condition_codes
OPTIONAL MATCH (s)-[:DELIVERED_BY]->(sp:Specialty)
RETURN patient.id AS patient_id, c.code AS condition_code, c.name AS condition_name,
       s.name AS service, r.interval_days AS interval_days,
       r.evidence_source AS evidence_source, sp.name AS specialty
"""

AGE_QUERY_BATCH = """
UNWIND $patients AS patient
MATCH (a:AgeBand)-[r:SCREENING_DUE]->(s:Service)
WHERE patient.age >= a.min_age AND patient.age <= a.max_age
OPTIONAL MATCH (s)-[:DELIVERED_BY]->(sp:Specialty)
RETURN patient.id AS patient_id, NULL AS condition_code, 'age-based screening' AS condition_name,
       s.name AS service, r.interval_days AS interval_days,
       r.evidence_source AS evidence_source, sp.name AS specialty
"""


@lru_cache(maxsize=1)
def _driver():
    user = get_secret("neo4j", "user", "NEO4J_USER") or "neo4j"
    password = get_secret("neo4j", "password", "NEO4J_PASSWORD") or "velo_secret"
    return GraphDatabase.driver(NEO4J_URI, auth=(user, password))


def _pick_most_overdue(candidates: list[dict], days_since_last_visit: int) -> dict | None:
    overdue = [
        c for c in candidates
        if c["interval_days"] is not None and days_since_last_visit > c["interval_days"]
    ]
    if not overdue:
        return None
    # Most overdue (largest gap past its own interval) wins.
    overdue.sort(key=lambda c: days_since_last_visit - c["interval_days"], reverse=True)
    top = overdue[0]
    return {
        "condition_code":         top["condition_code"],
        "condition_name":         top["condition_name"],
        "service":                top["service"],
        "specialty":              top["specialty"],
        "interval_days":          top["interval_days"],
        "days_since_last_visit":  days_since_last_visit,
        "overdue_by_days":        days_since_last_visit - top["interval_days"],
        "evidence_source":        top["evidence_source"],
    }


def clinical_recall_due_batch(patients: list[dict], as_of: date) -> dict[str, dict | None]:
    """Batched version of clinical_recall_due — one Neo4j session, at most 2
    queries total regardless of how many patients are passed in, instead of
    a session + up to 2 queries per patient.

    Each entry in `patients` needs: id, condition_codes, age,
    days_since_last_visit. Returns {patient_id: evidence_or_None}, covering
    every id passed in (including those with no due recall, mapped to None).
    """
    results: dict[str, dict | None] = {p["id"]: None for p in patients}

    with_conditions = [
        {"id": p["id"], "condition_codes": list(p["condition_codes"])}
        for p in patients if p.get("condition_codes") and p.get("days_since_last_visit") is not None
    ]
    with_age = [
        {"id": p["id"], "age": p["age"]}
        for p in patients if p.get("age") is not None and p.get("days_since_last_visit") is not None
    ]

    candidates_by_patient: dict[str, list[dict]] = {}
    with _driver().session() as session:
        if with_conditions:
            for record in session.run(CONDITION_QUERY_BATCH, patients=with_conditions):
                row = dict(record)
                candidates_by_patient.setdefault(row["patient_id"], []).append(row)
        if with_age:
            for record in session.run(AGE_QUERY_BATCH, patients=with_age):
                row = dict(record)
                candidates_by_patient.setdefault(row["patient_id"], []).append(row)

    for p in patients:
        days_since_last_visit = p.get("days_since_last_visit")
        if days_since_last_visit is None:
            continue
        candidates = candidates_by_patient.get(p["id"], [])
        if candidates:
            results[p["id"]] = _pick_most_overdue(candidates, days_since_last_visit)

    return results


def clinical_recall_due(
    condition_codes: list[str] | None,
    age: int | None,
    days_since_last_visit: int | None,
    as_of: date,
) -> dict | None:
    """Single-patient convenience wrapper over clinical_recall_due_batch —
    kept for callers that only ever need one patient at a time. The live
    daily pipeline (evaluate_rules) calls the batch version directly."""
    result = clinical_recall_due_batch(
        [{
            "id": "_single",
            "condition_codes": condition_codes,
            "age": age,
            "days_since_last_visit": days_since_last_visit,
        }],
        as_of,
    )
    return result["_single"]
