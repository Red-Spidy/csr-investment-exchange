#!/usr/bin/env bash
# 06_concurrency.sh -- two sessions race to fund the SAME project simultaneously.
# Exactly one must win. This is the live demo for the atomic-commitment claim.
set -uo pipefail

PSQL="docker exec -i csr_db psql -U csr -d csr_exchange -qtAX"

# Teardown must explicitly suspend the append-only ledger guard. That guard
# blocks cascade deletes too -- you cannot erase financial history by deleting
# the parent company -- which is the behaviour we want in production and the
# reason teardown has to opt out of it in the open.
cleanup() {
  $PSQL -v ON_ERROR_STOP=1 >/dev/null 2>&1 <<'SQL'
BEGIN;
ALTER TABLE fund_transactions DISABLE TRIGGER trg_ledger_immutable;
DELETE FROM companies WHERE cin = 'T-RACE-CIN';
DELETE FROM ngos      WHERE registration_no = 'T-RACE-NGO';
ALTER TABLE fund_transactions ENABLE TRIGGER trg_ledger_immutable;
COMMIT;
SQL
}
trap cleanup EXIT
cleanup

# fixture: one approved project, one company with budget for exactly one commitment
read -r NGO_ID < <($PSQL -c "INSERT INTO ngos (name, registration_no, sector)
                             VALUES ('Race NGO','T-RACE-NGO','education') RETURNING id;")
read -r CO_ID  < <($PSQL -c "INSERT INTO companies (name, cin, fy, avg_net_profit, mandated_csr_budget)
                             VALUES ('Race Co','T-RACE-CIN','FY24-25', 5000000, 500000) RETURNING id;")
read -r PR_ID  < <($PSQL -c "INSERT INTO projects (ngo_id, title, proposal_text, sector,
                                                   requested_amount, duration_months, num_phases, status)
                             VALUES ($NGO_ID,'Race project','text','education',100000,6,2,'approved')
                             RETURNING id;")

echo "   fixture: company=$CO_ID project=$PR_ID"

# Both sessions open a transaction, pause so they genuinely overlap, then commit funds.
race() {
  $PSQL -v ON_ERROR_STOP=1 <<SQL 2>&1
BEGIN;
SELECT pg_sleep(0.4);
SELECT fn_commit_funds($CO_ID, $PR_ID, NULL, 100000);
COMMIT;
SQL
}

race > /tmp/race_a.log & PID_A=$!
race > /tmp/race_b.log & PID_B=$!
wait $PID_A; RC_A=$?
wait $PID_B; RC_B=$?

echo "   session A exit=$RC_A | session B exit=$RC_B"

FAILURES=0
assert() { # assert <description> <actual> <expected>
  if [ "$2" != "$3" ]; then
    echo "   FAIL: $1 -- got '$2', expected '$3'"; FAILURES=$((FAILURES+1))
  fi
}

# exactly one session succeeded
if [ $((RC_A == 0 ? 1 : 0)) -eq $((RC_B == 0 ? 1 : 0)) ]; then
  echo "   FAIL: expected exactly one winner (A=$RC_A B=$RC_B)"; FAILURES=$((FAILURES+1))
fi

ACTIVE=$($PSQL -c "SELECT count(*) FROM commitments WHERE project_id=$PR_ID AND status='active';")
BUDGET=$($PSQL -c "SELECT committed_budget FROM companies WHERE id=$CO_ID;")
LOCKS=$($PSQL  -c "SELECT count(*) FROM fund_transactions ft
                     JOIN commitments c ON c.id=ft.commitment_id
                    WHERE c.project_id=$PR_ID AND ft.txn_type='lock';")
PHASES=$($PSQL -c "SELECT count(*) FROM fund_phases fp
                     JOIN commitments c ON c.id=fp.commitment_id
                    WHERE c.project_id=$PR_ID;")

assert "active commitments"      "$ACTIVE" "1"
assert "committed_budget"        "$BUDGET" "100000.00"
assert "ledger lock rows"        "$LOCKS"  "1"
assert "generated fund phases"   "$PHASES" "2"

if [ "$FAILURES" -eq 0 ]; then
  echo "   PASS 06_concurrency: one winner, budget consistent, no duplicate ledger rows"
  exit 0
fi
echo "   loser output:"; grep -h ERROR /tmp/race_a.log /tmp/race_b.log | sed 's/^/     /'
exit 1
