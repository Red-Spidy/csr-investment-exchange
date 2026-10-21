#!/usr/bin/env bash
# 09_terminate_race.sh -- a verification and a termination hit the same commitment at
# the same moment, in both orders. Money must never be paid and refunded twice, and a
# deadlock fails the run. It cannot prove the lock order in fn_terminate_commitment is
# deadlock-free: a verification takes all its locks in one statement, so the two sessions
# never interleave mid-way. Set DB_CONTAINER to test a database other than csr_db.
set -uo pipefail

PSQL="docker exec -i ${DB_CONTAINER:-csr_db} psql -U csr -d csr_exchange -qtAX"

# Teardown opts out of the append-only ledger in the open, as 06_concurrency.sh does,
# and clears the audit rows too: audit_log has no foreign key to cascade through.
cleanup() {
  $PSQL -v ON_ERROR_STOP=1 >/dev/null 2>&1 <<'SQL'
BEGIN;
DELETE FROM audit_log
 WHERE (entity = 'commitment' AND entity_id IN (SELECT c.id FROM commitments c
            JOIN companies co ON co.id = c.company_id WHERE co.cin LIKE 'T-TRACE-%'))
    OR (entity = 'milestone'  AND entity_id IN (SELECT m.id FROM milestones m
            JOIN commitments c ON c.id = m.commitment_id
            JOIN companies co ON co.id = c.company_id WHERE co.cin LIKE 'T-TRACE-%'));
ALTER TABLE fund_transactions DISABLE TRIGGER trg_ledger_immutable;
DELETE FROM companies WHERE cin LIKE 'T-TRACE-%';
DELETE FROM ngos      WHERE registration_no LIKE 'T-TRACE-%';
ALTER TABLE fund_transactions ENABLE TRIGGER trg_ledger_immutable;
COMMIT;
SQL
}
trap cleanup EXIT
cleanup

FAILURES=0
assert() { # assert <description> <actual> <expected>
  if [ "$2" != "$3" ]; then
    echo "   FAIL: $1 -- got '$2', expected '$3'"; FAILURES=$((FAILURES+1))
  fi
}

# fixture: a committed 300,000 project in 3 phases whose first milestone has evidence in
fixture() { # fixture <tag>  -> sets CO and CM
  local ngo pr
  read -r ngo < <($PSQL -c "INSERT INTO ngos (name, registration_no, sector)
                            VALUES ('Term race NGO $1','T-TRACE-NGO-$1','education') RETURNING id;")
  read -r CO  < <($PSQL -c "INSERT INTO companies (name, cin, fy, avg_net_profit, mandated_csr_budget)
                            VALUES ('Term race Co $1','T-TRACE-CIN-$1','FY24-25', 5000000, 500000) RETURNING id;")
  read -r pr  < <($PSQL -c "INSERT INTO projects (ngo_id, title, proposal_text, sector,
                                                  requested_amount, duration_months, num_phases, status)
                            VALUES ($ngo,'Term race project $1','text','education',300000,9,3,'approved')
                            RETURNING id;")
  read -r CM  < <($PSQL -c "SELECT fn_commit_funds($CO, $pr, NULL, 300000);")
  $PSQL -c "UPDATE milestones SET verification_status='submitted'
             WHERE commitment_id=$CM AND phase_no=1;" >/dev/null
}

books() { # books <commitment> -> lock | release | terminate | refund | budget
  $PSQL -c "SELECT
      COALESCE(SUM(amount) FILTER (WHERE txn_type='lock'), 0)      || ' | ' ||
      COALESCE(SUM(amount) FILTER (WHERE txn_type='release'), 0)   || ' | ' ||
      COALESCE(SUM(amount) FILTER (WHERE txn_type='terminate'), 0) || ' | ' ||
      COALESCE(SUM(amount) FILTER (WHERE txn_type='refund'), 0)    || ' | ' ||
      (SELECT committed_budget FROM companies WHERE id=$CO)
    FROM fund_transactions WHERE commitment_id=$1;"
}

VERIFY="UPDATE milestones SET verification_status='verified', verified_by='B'
         WHERE commitment_id=%CM% AND phase_no=1;"
TERMINATE="SELECT fn_terminate_commitment(%CM%, 'race', 'A');"
sql() { echo "${1//%CM%/$CM}"; }

# --- 1: the verification holds its locks first; the termination must wait and then
#        refund only what is still unreleased.
fixture 1
{ echo "BEGIN;"; sql "$VERIFY"; echo "SELECT pg_sleep(1.5); COMMIT;"; } \
  | $PSQL -v ON_ERROR_STOP=1 >/tmp/trace_b.log 2>&1 & PID_B=$!
sleep 0.5
sql "$TERMINATE" | $PSQL -v ON_ERROR_STOP=1 >/tmp/trace_a.log 2>&1; RC_A=$?
wait $PID_B; RC_B=$?

assert "1: verification exit"   "$RC_B" "0"
assert "1: termination exit"    "$RC_A" "0"
assert "1: refund"              "$(cat /tmp/trace_a.log)" "200000.00"
assert "1: phases" "$($PSQL -c "SELECT string_agg(status::text, ',' ORDER BY phase_no) FROM fund_phases WHERE commitment_id=$CM;")" \
                   "released,terminated,terminated"
assert "1: lock | release | terminate | refund | budget" "$(books "$CM")" "300000.00 | 100000.00 | 200000.00 | 200000.00 | 100000.00"

# --- 2: the termination holds its locks first; the verification must be refused.
fixture 2
{ echo "BEGIN;"; sql "$TERMINATE"; echo "SELECT pg_sleep(1.5); COMMIT;"; } \
  | $PSQL -v ON_ERROR_STOP=1 >/tmp/trace_a.log 2>&1 & PID_A=$!
sleep 0.5
sql "$VERIFY" | $PSQL -v ON_ERROR_STOP=1 >/tmp/trace_b.log 2>&1; RC_B=$?
wait $PID_A; RC_A=$?

assert "2: termination exit"    "$RC_A" "0"
assert "2: verification refused" "$RC_B" "3"
assert "2: reason" "$(grep -c 'its milestones can no longer change' /tmp/trace_b.log)" "1"
assert "2: milestone left as submitted" \
       "$($PSQL -c "SELECT verification_status FROM milestones WHERE commitment_id=$CM AND phase_no=1;")" "submitted"
assert "2: phases" "$($PSQL -c "SELECT string_agg(status::text, ',' ORDER BY phase_no) FROM fund_phases WHERE commitment_id=$CM;")" \
                   "terminated,terminated,terminated"
assert "2: lock | release | terminate | refund | budget" "$(books "$CM")" "300000.00 | 0 | 300000.00 | 300000.00 | 0.00"

if grep -qi deadlock /tmp/trace_a.log /tmp/trace_b.log; then
  echo "   FAIL: a session reported a deadlock"; FAILURES=$((FAILURES+1))
fi
rm -f /tmp/trace_a.log /tmp/trace_b.log

if [ "$FAILURES" -eq 0 ]; then
  echo "   PASS 09_terminate_race: both orders end consistent, no double payment"
  exit 0
fi
exit 1
