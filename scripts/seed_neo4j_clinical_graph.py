#!/usr/bin/env python3
"""Seed the VE Graph clinical-recall knowledge graph in Neo4j.

Physician-reviewable guideline matrix, expressed as data (not code), matching
the schema in the master spec:

    (:Condition)-[:REQUIRES_FOLLOWUP {interval_days, evidence_source}]->(:Service)
    (:AgeBand)-[:SCREENING_DUE {interval_days, evidence_source}]->(:Service)
    (:Condition)-[:IMPLIES_REFERRAL]->(:Specialty)
    (:Service)-[:DELIVERED_BY]->(:Specialty)

Idempotent — safe to re-run (everything is MERGE'd, never duplicated).
Condition codes match what's actually in patient_features.condition_codes
for the seeded synthetic cohort (E11, I10, J45, N18, E78, Z87.891, K21).
"""

import os

from neo4j import GraphDatabase

NEO4J_URI      = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "velo_secret")

# Each row: condition code, name, recall service, interval (days), evidence
# source, referral specialty.
CONDITION_RECALLS = [
    ("E11", "Type 2 diabetes mellitus", "HbA1c monitoring", 90,
     "ADA Standards of Care", "Endocrinology"),
    ("E11", "Type 2 diabetes mellitus", "Diabetic retinal exam", 365,
     "ADA Standards of Care", "Ophthalmology"),
    ("I10", "Essential hypertension", "Blood pressure recheck", 180,
     "ACC/AHA Hypertension Guideline", "Cardiology"),
    ("J45", "Asthma", "Pulmonary function review", 365,
     "GINA Asthma Guideline", "Pulmonology"),
    ("N18", "Chronic kidney disease", "Renal function panel", 90,
     "KDIGO CKD Guideline", "Nephrology"),
    ("E78", "Dyslipidemia", "Lipid panel", 180,
     "ACC/AHA Cholesterol Guideline", "Cardiology"),
    ("Z87.891", "Personal history of nicotine dependence", "Smoking cessation review", 365,
     "USPSTF Tobacco Use Guideline", "Primary Care"),
    ("K21", "Gastro-esophageal reflux disease", "GI follow-up", 365,
     "ACG GERD Guideline", "Gastroenterology"),
]

# Each row: min_age, max_age, service, interval (days), evidence source,
# specialty.
AGE_BAND_SCREENINGS = [
    (40, 120, "Annual wellness review", 365,
     "Preventive care guideline", "Primary Care"),
    (50, 75, "Colonoscopy screening", 3650,
     "USPSTF Colorectal Cancer Screening", "Gastroenterology"),
]


def seed(driver):
    with driver.session() as session:
        for code, name, service, interval_days, evidence, specialty in CONDITION_RECALLS:
            session.run(
                """
                MERGE (c:Condition {code: $code})
                  SET c.name = $name
                MERGE (s:Service {name: $service})
                MERGE (c)-[r:REQUIRES_FOLLOWUP]->(s)
                  SET r.interval_days = $interval_days, r.evidence_source = $evidence
                MERGE (sp:Specialty {name: $specialty})
                MERGE (c)-[:IMPLIES_REFERRAL]->(sp)
                MERGE (s)-[:DELIVERED_BY]->(sp)
                """,
                code=code, name=name, service=service,
                interval_days=interval_days, evidence=evidence, specialty=specialty,
            )
            print(f"  [Condition] {code} ({name}) -> {service} every {interval_days}d -> {specialty}")

        for min_age, max_age, service, interval_days, evidence, specialty in AGE_BAND_SCREENINGS:
            session.run(
                """
                MERGE (a:AgeBand {min_age: $min_age, max_age: $max_age})
                MERGE (s:Service {name: $service})
                MERGE (a)-[r:SCREENING_DUE]->(s)
                  SET r.interval_days = $interval_days, r.evidence_source = $evidence
                MERGE (sp:Specialty {name: $specialty})
                MERGE (s)-[:DELIVERED_BY]->(sp)
                """,
                min_age=min_age, max_age=max_age, service=service,
                interval_days=interval_days, evidence=evidence, specialty=specialty,
            )
            print(f"  [AgeBand {min_age}-{max_age}] -> {service} every {interval_days}d -> {specialty}")


if __name__ == "__main__":
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        seed(driver)
        print("\nVE Graph clinical-recall knowledge graph seeded.")
    finally:
        driver.close()
