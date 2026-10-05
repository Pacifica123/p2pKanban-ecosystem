#!/bin/sh
set -eu

SECRETS_DIR=/run/p2pkanban-secrets

read_secret() {
  path="$1"
  if [ ! -s "$path" ]; then
    echo "Required bootstrap secret is missing: $path" >&2
    exit 1
  fi
  tr -d '\r\n' < "$path"
}

postgres_password="$(read_secret "$SECRETS_DIR/postgres-password")"
jwt_secret="$(read_secret "$SECRETS_DIR/jwt-secret")"
nostr_secret_key="$(read_secret "$SECRETS_DIR/nostr-secret-key")"
nostr_master_key="$(read_secret "$SECRETS_DIR/nostr-master-key")"

export DATABASE__URL="postgres://p2pkanban:${postgres_password}@postgres:5432/p2pkanban"
export AUTH__JWT_SECRET="$jwt_secret"
export TRANSPORTS__NOSTR__SECRET_KEY="$nostr_secret_key"
export TRANSPORTS__NOSTR__MASTER_KEY_BASE64="$nostr_master_key"

unset postgres_password jwt_secret nostr_secret_key nostr_master_key
exec /usr/local/bin/p2p-planner-backend "$@"
