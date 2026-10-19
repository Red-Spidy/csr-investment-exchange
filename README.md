# CSR Investment Exchange

AI-scored, SQL-automated matching of corporate CSR budgets to NGO projects.
Companion implementation for the ADV_SQL review deck.

## Quick start

```bash
docker compose up -d          # or: make up
make migrate seed             # schema + demo scenario
make test                     # DB assertions
make psql                     # poke around
```

Postgres listens on **localhost:5433** (5433, not 5432, to avoid colliding with
a local install).

## Layout

| Path | What it is |
|---|---|
| `db/migrations/` | Schema, triggers, window views, pgvector matching. Applied in filename order. |
| `db/tests/` | Assertion tests. Each `RAISE`s on failure, so a non-zero exit is a real regression. |
| `db/seed.sql` | Deterministic demo scenario. |
| `ml/` | BERT, XGBoost and Isolation Forest, trained on synthetic project data (not yet built). |
| `api/`, `web/` | FastAPI + React (not yet built). |

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

## Status

Built and verified:

- Full schema, triggers, transactions, window views, pgvector matching
- 10/10 DB assertions pass from a clean `reset`
- Two-session concurrency test passes

Not yet built: synthetic training datasets, NLP & SDG extraction (BERT), impact
prediction (XGBoost), fraud detection (Isolation Forest), composite risk
grading, pipeline runner, FastAPI layer, React frontend.

Until the models exist, the extraction, impact, fraud and risk-grade rows in
`db/seed.sql` are hand-written placeholders, and its embeddings are synthetic
topic vectors. They keep the matching demo reproducible; the trained models
will replace them.
