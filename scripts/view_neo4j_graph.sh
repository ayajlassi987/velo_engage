#!/usr/bin/env bash
# Prints the clinical-recall knowledge graph currently seeded in Neo4j.
# Safe to run anytime — read-only, same output every time unless the
# seed script (seed_neo4j_clinical_graph.py) is re-run with different data.
set -euo pipefail

CYPHER_SHELL="docker exec ve_neo4j cypher-shell -u neo4j -p velo_secret"

echo "=== Conditions -> required follow-up service -> interval ==="
$CYPHER_SHELL "MATCH (c:Condition)-[r:REQUIRES_FOLLOWUP]->(s:Service) RETURN c.code, c.name, s.name, r.interval_days, r.evidence_source ORDER BY c.code;"

echo
echo "=== Service -> delivering specialty ==="
$CYPHER_SHELL "MATCH (s:Service)-[:DELIVERED_BY]->(sp:Specialty) RETURN s.name, sp.name ORDER BY s.name;"

echo
echo "=== Age-band screening rules ==="
$CYPHER_SHELL "MATCH (a:AgeBand)-[r:SCREENING_DUE]->(s:Service) RETURN a.min_age, a.max_age, s.name, r.interval_days ORDER BY a.min_age;"

echo
echo "=== Node/relationship counts ==="
$CYPHER_SHELL "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS count ORDER BY label;"
$CYPHER_SHELL "MATCH ()-[r]->() RETURN type(r) AS relationship, count(*) AS count ORDER BY relationship;"

echo
echo "For the visual graph view, open http://localhost:7474 (login neo4j / velo_secret) and run:"
echo "  MATCH (c:Condition)-[r:REQUIRES_FOLLOWUP]->(s:Service)-[:DELIVERED_BY]->(sp:Specialty) RETURN c, r, s, sp"
