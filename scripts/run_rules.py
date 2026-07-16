#!/usr/bin/env python3
"""Evaluate enabled YAML opportunity policies and write opportunity rows."""

import json
import sys
import uuid
from datetime import date
from pathlib import Path

import psycopg2

ORCHESTRATOR_SRC = Path(__file__).parents[1] / "services" / "ve_orchestrator" / "src"
sys.path.insert(0, str(ORCHESTRATOR_SRC))

from ve_orchestrator.policy_engine import active_policies, evaluate_policy  # noqa: E402

PG = dict(host="localhost", port=5432, dbname="velodb", user="velo", password="velo_secret")
CLINIC_ID = "clinic_alnoor_001"


def run_rules(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT patient_id, to_jsonb(pf) - 'patient_id' - 'clinic_id'
        FROM patient_features pf
        WHERE clinic_id = %s
        """,
        (CLINIC_ID,),
    )
    rows = cur.fetchall()
    today = date.today()
    policies = active_policies()
    opportunities = []

    for pid, features in rows:
        for policy in policies:
            evidence = evaluate_policy(policy, features, today)
            if evidence is None:
                continue
            rule = policy["rule"]
            opportunity = {
                "opportunity_id": str(uuid.uuid4()),
                "patient_id": pid,
                "clinic_id": CLINIC_ID,
                "family": policy["family"],
                "consent_class": rule["consent_class"],
                "priority_score": rule["priority"],
                "rule_name": rule["id"],
                "rule_evidence": evidence,
            }
            opportunities.append(opportunity)
            print(f"  [{policy['family']}] {pid} - {rule['id']}")

    for opportunity in opportunities:
        cur.execute(
            """
            INSERT INTO opportunities
              (opportunity_id, patient_id, clinic_id, family, consent_class,
               priority_score, rule_name, rule_evidence)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING
            """,
            (
                opportunity["opportunity_id"], opportunity["patient_id"],
                opportunity["clinic_id"], opportunity["family"],
                opportunity["consent_class"], opportunity["priority_score"],
                opportunity["rule_name"], json.dumps(opportunity["rule_evidence"]),
            ),
        )

    conn.commit()
    cur.close()
    print(f"\n{len(opportunities)} opportunities written to Postgres")
    return opportunities


if __name__ == "__main__":
    connection = psycopg2.connect(**PG)
    try:
        run_rules(connection)
    finally:
        connection.close()
