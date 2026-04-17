#!/bin/sh
set -eu

echo "Waiting for Vault..."
until wget -q -O - "${VAULT_ADDR}/v1/sys/health" >/dev/null 2>&1; do
  sleep 1
done

echo "Writing development secrets to Vault..."

vault kv put secret/fastapi-saas-template \
  database_url="postgresql+psycopg://app:app@postgres:5432/app" \
  redis_url="redis://redis:6379/0" \
  keycloak_client_secret="dev-keycloak-secret"

echo "Vault initialization complete."