#!/usr/bin/env bash
# The offline demo in the browser is a port of the database rules. This checks the port
# against the real thing: rebuild the database from the seed without scoring it, start the
# API on a spare port, and run web/src/data/parity.test.ts with its reads and writes.
#
#   make test-parity
#
# It replaces the demo data with the unscored seed. make demo-check, or Reset demo data in
# the review console, rebuilds and rescores it.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT=${PARITY_PORT:-8022}
DB_URL=${DB_URL:-postgresql://csr:csr@localhost:5433/csr_exchange}
mkdir -p demo-check

make demo >/dev/null
# Rating off: the browser's offline engine never rates, so both sides stay comparable.
DATABASE_URL=$DB_URL CSR_ALLOW_RESET=1 CSR_RATER=off .venv/bin/python -m uvicorn app.main:app --app-dir api \
  --host 127.0.0.1 --port "$PORT" > demo-check/parity-api.log 2>&1 &
API=$!
trap 'kill $API 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && break
  sleep 0.5
done

cd web
VITE_PARITY_API_URL="http://127.0.0.1:$PORT" VITE_PARITY_WRITES=1 npx vitest run src/data/parity.test.ts
