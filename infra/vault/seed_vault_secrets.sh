#!/bin/sh
# Populates Vault's KV store from whatever's in the environment this
# container was started with (see the vault-seed service's env_file/
# environment in docker-compose.dev.yml, which points at the same .env
# files the services previously read directly). Safe to re-run: `vault kv
# put` is a plain overwrite (versioned by Vault's KV v2 engine, never an
# error to repeat) — same idempotent-on-rerun contract as the Neo4j seed
# script and the Keycloak realm import.
#
# Vault here runs in dev mode (`-dev`), which is hardcoded to in-memory
# storage — every secret below is lost on a Vault container restart, which
# is exactly why this runs as a startup step every time, not a one-off
# manual command. Before any real production deployment this needs a real
# storage backend (file/Raft/Consul) and proper unsealing, not dev mode —
# see PROJECT_STATUS.md.
set -eu

echo "Seeding Vault secrets at $VAULT_ADDR..."

vault kv put secret/postgres \
  user="${DB_USER}" \
  password="${DB_PASSWORD}"

vault kv put secret/neo4j \
  user="${NEO4J_USER}" \
  password="${NEO4J_PASSWORD}"

vault kv put secret/keycloak \
  client_secret="${KEYCLOAK_CLIENT_SECRET}" \
  session_secret="${SESSION_SECRET}" \
  admin_password="${KEYCLOAK_ADMIN_PASSWORD}"

vault kv put secret/ngrok \
  authtoken="${NGROK_AUTHTOKEN}"

vault kv put secret/whatsapp \
  access_token="${WHATSAPP_ACCESS_TOKEN}" \
  phone_number_id="${WHATSAPP_PHONE_NUMBER_ID}" \
  business_account_id="${WHATSAPP_BUSINESS_ACCOUNT_ID}" \
  webhook_verify_token="${WEBHOOK_VERIFY_TOKEN}"

vault kv put secret/twilio \
  account_sid="${TWILIO_ACCOUNT_SID}" \
  auth_token="${TWILIO_AUTH_TOKEN}" \
  from_number="${TWILIO_FROM_NUMBER}"

vault kv put secret/epic \
  client_id="${EPIC_CLIENT_ID}" \
  client_secret="${EPIC_CLIENT_SECRET}"

vault kv put secret/epic_bulk \
  client_id="${EPIC_BULK_CLIENT_ID}" \
  group_id="${EPIC_BULK_GROUP_ID}" \
  token_url="${EPIC_BULK_TOKEN_URL}" \
  kid="${EPIC_BULK_KID}" \
  private_key_b64="${EPIC_BULK_PRIVATE_KEY_B64}"

echo "Vault seeding complete."
