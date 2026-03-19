#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT_DIR/saki-api"
GO_DIR="$ROOT_DIR/saki-controlplane"
SCHEMA_PATH="$ROOT_DIR/shared/db/schema.sql"

MODE_RESET=false
MODE_DOCKER=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset)
      MODE_RESET=true
      shift
      ;;
    --docker)
      MODE_DOCKER=true
      shift
      ;;
    *)
      echo "Usage: $0 [--reset] [--docker]" >&2
      exit 1
      ;;
  esac
done

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing dependency: $1" >&2
    exit 1
  fi
}

require_cmd uv
require_cmd sqlc

if [[ "$MODE_DOCKER" == true ]]; then
  require_cmd docker
else
  require_cmd psql
  require_cmd pg_dump
fi

cd "$API_DIR"
if ! uv run alembic --version >/dev/null 2>&1; then
  echo "Missing dependency: alembic (via uv)" >&2
  exit 1
fi

if [[ -z "${DATABASE_URL:-}" && -f "$API_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$API_DIR/.env"
  set +a
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is not set." >&2
  exit 1
fi

PSQL_URL="$(printf '%s' "$DATABASE_URL" | sed 's/^postgresql+psycopg:\/\//postgresql:\/\//')"

DB_USER=""
DB_PASSWORD=""
DB_HOST=""
DB_PORT=""
DB_NAME=""

parse_database_url() {
  local url="$1"
  local without_scheme auth_and_host auth hostport db_and_params

  without_scheme="${url#*://}"
  auth_and_host="${without_scheme%%/*}"
  db_and_params="${without_scheme#*/}"
  DB_NAME="${db_and_params%%\?*}"

  if [[ "$auth_and_host" == *"@"* ]]; then
    auth="${auth_and_host%@*}"
    hostport="${auth_and_host#*@}"
    if [[ "$auth" == *":"* ]]; then
      DB_USER="${auth%%:*}"
      DB_PASSWORD="${auth#*:}"
    else
      DB_USER="$auth"
      DB_PASSWORD=""
    fi
  else
    hostport="$auth_and_host"
    DB_USER=""
    DB_PASSWORD=""
  fi

  if [[ "$hostport" == *":"* ]]; then
    DB_HOST="${hostport%%:*}"
    DB_PORT="${hostport#*:}"
  else
    DB_HOST="$hostport"
    DB_PORT=""
  fi
}

parse_database_url "$PSQL_URL"
if [[ -z "$DB_USER" ]]; then
  DB_USER="postgres"
fi
if [[ -z "$DB_NAME" ]]; then
  DB_NAME="postgres"
fi

DOCKER_EXEC=()
if [[ "$MODE_DOCKER" == true ]]; then
  if command -v docker-compose >/dev/null 2>&1; then
    DOCKER_EXEC=(docker-compose -f "$ROOT_DIR/docker-compose.yml" exec -T postgres)
  else
    DOCKER_EXEC=(docker compose -f "$ROOT_DIR/docker-compose.yml" exec -T postgres)
  fi
  if ! "${DOCKER_EXEC[@]}" true </dev/null >/dev/null 2>&1; then
    DOCKER_EXEC=(docker exec -i saki-postgres)
  fi
fi

mkdir -p "$(dirname "$SCHEMA_PATH")"

if [[ "$MODE_RESET" == true ]]; then
  read -r -p "This will DROP SCHEMA public and delete migrations. Continue? (Y/n) " confirm
  if [[ -n "$confirm" && "$confirm" != "Y" && "$confirm" != "y" ]]; then
    echo "Aborted."
    exit 0
  fi

  echo "Mode 2: Hard Reset"
  if [[ "$MODE_DOCKER" == true ]]; then
    if [[ -n "$DB_PASSWORD" ]]; then
      "${DOCKER_EXEC[@]}" env PGPASSWORD="$DB_PASSWORD" \
        psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
        -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    else
      "${DOCKER_EXEC[@]}" psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
        -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    fi
  else
    psql "$PSQL_URL" -v ON_ERROR_STOP=1 -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
  fi
  echo "Step OK: schema reset"

  find "$API_DIR/alembic/versions" -type f -name "*.py" ! -name "__init__.py" -delete
  echo "Step OK: migrations cleaned"

  uv run alembic revision --autogenerate -m "init_schema"
  echo "Step OK: init_schema migration generated"

  uv run alembic upgrade head
  echo "Step OK: migrations applied"
else
  echo "Mode 1: Sync"
  uv run alembic upgrade head
  echo "Step OK: migrations applied"
fi

if [[ "$MODE_DOCKER" == true ]]; then
  if [[ -n "$DB_PASSWORD" ]]; then
    "${DOCKER_EXEC[@]}" env PGPASSWORD="$DB_PASSWORD" \
      pg_dump -U "$DB_USER" -d "$DB_NAME" --schema-only --no-owner --no-privileges \
      | sed '/^\\\\/d' > "$SCHEMA_PATH"
  else
    "${DOCKER_EXEC[@]}" pg_dump -U "$DB_USER" -d "$DB_NAME" --schema-only --no-owner --no-privileges \
      | sed '/^\\\\/d' > "$SCHEMA_PATH"
  fi
else
  pg_dump --schema-only --no-owner --no-privileges "$PSQL_URL" | sed '/^\\\\/d' > "$SCHEMA_PATH"
fi
sed -i.bak '/^\\/d' "$SCHEMA_PATH" && rm -f "$SCHEMA_PATH.bak"
echo "Step OK: schema exported to $SCHEMA_PATH"

cd "$GO_DIR"
sqlc generate
echo "Step OK: sqlc generate completed"
