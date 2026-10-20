# CSR Investment Exchange

AI-scored, SQL-automated matching of corporate CSR budgets to NGO projects.
Companion implementation for the ADV_SQL review deck.

## Quick start

```bash
docker compose up -d          # or: make up
make migrate seed             # schema + demo scenario
make test                     # DB assertions, API tests, ML tests
make psql                     # poke around

make api                                # FastAPI on http://localhost:8000
cd web && npm install && npm run dev    # frontend on http://localhost:5173
```

The frontend looks for the API when it starts. If it answers, every number comes
from Postgres. If it does not, the frontend falls back to an in-browser copy of
the database rules, and the sidebar says which one you are looking at.

Postgres listens on **localhost:5433** (5433, not 5432, to avoid colliding with
a local install).

## Layout

| Path | What it is |
|---|---|
| `db/migrations/` | Schema, triggers, window views, pgvector matching. Applied in filename order. |
| `db/tests/` | Assertion tests. Each `RAISE`s on failure, so a non-zero exit is a real regression. |
| `db/seed.sql` | Deterministic demo scenario. |
| `ml/` | BERT, XGBoost and Isolation Forest, trained on synthetic project data (not yet built). |
| `api/` | FastAPI over the database (`api/app`). Its tests (`api/tests`) run against real Postgres, in throwaway databases. |
| `web/` | React + TypeScript frontend. Uses the API when it is running, otherwise an in-browser demo store that ports the rules in `db/migrations/004` and `005`. |

## The Advanced SQL core

Each claim in the deck maps to code and to a test that proves it:

| Claim | Where | Proven by |
|---|---|---|
| Window functions track impact over time | `005_views_windows.sql` → `company_esg_timeline` | `04_window_functions.sql` (against hand-computed values) |
| pgvector matches inside the database | `fn_match_projects()` | `05_matching.sql` |
| Triggers release funds on milestone verification | `fn_release_next_phase()` | `01_triggers.sql` |
| Transactions make double-funding impossible | `fn_commit_funds()` | `02_double_funding.sql`, `06_concurrency.sh` |
| Failed verification holds funds | `fn_hold_on_failed_verification()` | `01_triggers.sql` |

**Anti-double-funding is three independent layers**, each tested separately
because the outer one short-circuits the others in normal operation:

1. `fn_commit_funds` rejects a project that is not `approved`.
2. A `BEFORE INSERT` guard trigger rejects a duplicate active commitment.
3. A partial unique index (`WHERE status='active'`) is the final backstop.

`06_concurrency.sh` races two live sessions at the same project. Exactly one
wins. **This is the test worth running live in front of the panel.**

The ledger (`fund_transactions`) is append-only, enforced by trigger. It blocks
cascade deletes too: you cannot erase funding history by deleting the company
that owns it.

**No model is in the fund-release path.** Models produce evidence; a human sets
a verification flag; a SQL trigger moves money.

## API

`api/app` implements `web/src/data/api.ts` over HTTP. Ranking, window functions and
every state change stay in SQL. The API calls `fn_commit_funds`, updates `milestones`
so the triggers fire, inserts `impact_reports` and reads the views, then reports what
the database did, or the exact error it raised.

| Route | What it runs |
|---|---|
| `GET /api/rulebooks/{id}/matches` | `fn_match_projects`, plus the rule that removed each other project |
| `GET /api/scorecard`, `/esg-timeline`, `/leaderboard` | the views `project_scorecard`, `company_esg_timeline`, `ngo_leaderboard` |
| `POST /api/commitments` | `fn_commit_funds` |
| `POST /api/milestones/{id}/evidence`, `/verify`, `/fail` | `UPDATE milestones`, which fires `trg_release_next_phase` or `trg_hold_on_failed_verification`. The API refuses to verify a milestone with no submitted evidence. |
| `POST /api/projects/{id}/impact-reports` | `INSERT INTO impact_reports` |
| `POST /api/ledger/{id}/attempts` | an `UPDATE` or `DELETE` on `fund_transactions`, always rolled back |
| `POST /api/safeguards/race` | two real sessions racing for one project, in a throwaway schema built from migrations 002 and 004 |
| `POST /api/reset` | rebuilds from `db/migrations` and `db/seed.sql`. Off unless `CSR_ALLOW_RESET=1` (`make api` sets it). |

A write the database refuses is an ordinary answer, not a server error: HTTP 200 with
`{"ok": false, "kind": "sql", "error": "<Postgres's own message>"}`. HTTP errors mean a
malformed request (422), an unknown id (404) or a database that cannot be reached (503).

**There is no authentication.** Whoever can reach the API can verify milestones and move
money, so run it on localhost or behind something that authenticates.

Tests: `make test-api` (creates and drops its own databases on the compose server, never
touching `csr_exchange`), and `cd web && npm test`. To check that the browser demo has not
drifted from the database, run `make api` against a freshly seeded database and then
`VITE_PARITY_API_URL=http://127.0.0.1:8000 npm test` in `web/`.

**Upgrading an existing database.** `006_fix_leaderboard_fanout.sql` fixes `ngo_leaderboard`,
which counted each commitment once per monthly report (the seeded 2,400,000 showed as
14,400,000). `make demo` rebuilds everything, or apply just that file:
`docker exec -i csr_db psql -U csr -d csr_exchange -f - < db/migrations/006_fix_leaderboard_fanout.sql`.

## Status

Built and verified:

- Full schema, triggers, transactions, window views, pgvector matching
- 11/11 DB assertions pass from a clean `reset`
- Two-session concurrency test passes
- FastAPI layer (`api/`) with tests against real Postgres, including a real two-session race
- React frontend (`web/`): six screens, on the API or on an in-browser demo store. `npm test` pins
  the demo's ported matching, window-view and trigger logic to numbers read from this database.

Not yet built: synthetic training datasets, NLP & SDG extraction (BERT), impact
prediction (XGBoost), fraud detection (Isolation Forest), composite risk
grading, pipeline runner.

Until the models exist, the extraction, impact, fraud and risk-grade rows in
`db/seed.sql` are hand-written placeholders, and its embeddings are synthetic
topic vectors. They keep the matching demo reproducible; the trained models
will replace them.
