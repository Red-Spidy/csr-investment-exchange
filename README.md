# CSR Investment Exchange

[![CI](https://github.com/Red-Spidy/csr-investment-exchange/actions/workflows/ci.yml/badge.svg)](https://github.com/Red-Spidy/csr-investment-exchange/actions/workflows/ci.yml)

AI-scored, SQL-automated matching of corporate CSR budgets to NGO projects.
Companion implementation for the ADV_SQL review deck.

## Quick start

```bash
docker compose up -d          # or: make up
make migrate seed             # schema + demo scenario
make test                     # DB assertions, API tests, ML tests
make psql                     # poke around

make train train-bert         # once: the three models (about 2 h, almost all of it BERT)
make score                    # replace the seed's placeholder scores with real model output

make api                                # FastAPI on http://localhost:8000
cd web && npm install && npm run dev    # frontend on http://localhost:5173
```

**Presenting?** Follow [`docs/demo.md`](docs/demo.md). `make demo-check` runs the deck's
whole workflow against the real stack, renders every page in headless Chrome, and leaves a
clean, scored demo.

The frontend opens on a sign-in page with three portals: an **NGO portal** (submit proposals,
report milestones), a **company CSR portal** (find projects, fund them, follow their impact) and
the **review console** (decide flagged proposals, verify evidence, run the safeguards). The demo
accounts have no passwords and the API has no authentication, so run it only on your own machine.

The frontend looks for the API when it starts. If it answers, every number comes
from Postgres. If it does not, the frontend falls back to an in-browser copy of
the database rules, and the sidebar says *Offline demo data* instead of *Connected*.

Postgres listens on **localhost:5433** (5433, not 5432, to avoid colliding with
a local install).

## Layout

| Path | What it is |
|---|---|
| `db/migrations/` | Schema, triggers, window views, pgvector matching. Applied in filename order. |
| `db/tests/` | Assertion tests. Each `RAISE`s on failure, so a non-zero exit is a real regression. |
| `db/seed.sql` | Deterministic demo scenario. |
| `ml/` | Synthetic training data (`synth`, `textgen`), the three models (`fraud`, `impact`, `nlp`) and the scoring pipeline (`pipeline`). How the data was made: `ml/datasets/README.md`. |
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
| Held money can be refunded, and the books still balance | `fn_terminate_commitment()` | `08_terminate.sql`, `09_terminate_race.sh` |
| A composite risk grade decides approval, in SQL | `fn_grade_project()`, `fn_review_project()` (`008_risk_grade.sql`) | `10_risk_grade.sql` |

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

**Held money has one way out.** A failed milestone holds its phase and nothing pays it
automatically. `fn_terminate_commitment` ends the commitment: released phases stay paid,
every locked or held phase is terminated and its money goes back to the company's budget,
and the ledger records each step, so what was locked always equals what was released plus
what was terminated. The project becomes `terminated` and cannot be funded again, and
`trg_guard_closed_commitment` freezes the milestones of any closed commitment. A held phase
also keeps its commitment open: before migration 007, paying a later phase completed the
commitment and stranded the held money for good.

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
| `POST /api/commitments/{id}/terminate` | `fn_terminate_commitment`. Body `{"reason": "..."}`; the reason and the reviewer (`CSR_REVIEWER`) go into the ledger and the audit log. |
| `POST /api/projects/{id}/impact-reports` | `INSERT INTO impact_reports`. Refused for a terminated project. |
| `POST /api/projects` | An NGO's proposal: `INSERT INTO projects` as `pending` and commit, then the trained models score it and `fn_grade_project` decides. The receipt says what each model found. If scoring fails, the proposal stays saved as `pending` and the receipt says why. |
| `POST /api/projects/{id}/review` | `fn_review_project`: approve or reject a project the grade sent to review. Body `{"approve": true, "note": "..."}`. |
| `POST /api/rulebooks` | A company's CSR requirements: `INSERT INTO csr_rulebooks`, then embedded with the same model as the projects so `fn_match_projects` can rank them at once. |
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
`VITE_PARITY_API_URL=http://127.0.0.1:8000 npm test` in `web/`. Adding `VITE_PARITY_WRITES=1`
also replays a fail-then-terminate scenario on both sides and compares the receipts and the
resulting state; it resets the database before and after, so only use it on a demo database.

**Upgrading an existing database.** `006_fix_leaderboard_fanout.sql` fixes `ngo_leaderboard`,
which counted each commitment once per monthly report (the seeded 2,400,000 showed as
14,400,000). `007_terminate_commitment.sql` adds termination and refunds, and changes
`ngo_leaderboard` to count only released money for a terminated commitment. `make demo`
rebuilds everything, or apply the files you are missing, in order:
`docker exec -i csr_db psql -U csr -d csr_exchange -f - < db/migrations/006_fix_leaderboard_fanout.sql`
(and the same for `007_terminate_commitment.sql`). 007 creates a function and a trigger, so
applying it twice fails; apply it once. `008_risk_grade.sql` adds the risk grade and manual
review; it also creates functions and a table, so apply it once too.

## The ML layer

Three models, trained on synthetic data built to be learnable but not trivial: hidden NGO
traits drive everything, and the models see only their noisy consequences
(`ml/datasets/README.md`). Every result below is on NGOs held out of training.

| Model | Job | Result | Details |
|---|---|---|---|
| Isolation Forest | Flags NGOs whose spending breaks their own pattern. Never sees a fraud label. | ROC-AUC 0.95; reviewing the top 10% of NGOs catches 22 of 30 fraudulent ones (grouped cross-validation) | `ml/results/fraud_metrics.json` |
| XGBoost | Forecasts the share of a proposal's claim that will be delivered, with an 80% interval, in the proposal's units | MAE 0.155 vs 0.184 for predicting the mean; R² 0.25 against an oracle ceiling of 0.35; the interval holds 79% of outcomes | `ml/results/impact_metrics.json` |
| 3 × BERT (`bert-base-cased`) | Reads a proposal: SDGs, outcome metric, stated facts. A fact the text does not state stays empty and becomes a red flag. | On 304 generated test proposals: SDG micro-F1 0.992, metric 100%, facts 99.9%, no invented facts. Rule baseline: 0.960, 75%, 99.8%, and it invents 2.5% of facts, fooled by counts of schools or villages | `ml/results/nlp_metrics.json` |

The BERT numbers are on text from the same generator it trained on. On the eight
hand-written demo proposals it does worse: it still reads "80,000 saplings" as a
beneficiary count and misses baselines phrased unusually ("only 54% of pregnant women
complete..."), though retraining with unlabelled counts fixed "12 schools" and "60 toilet
blocks" (`ml/pipeline/README.md`). The team-written test set in `ml/datasets/human_test/`
measures this properly.

`make score` writes all three models' evidence into the database, and `fn_grade_project`
decides. A grade of A or B with no fraud flag and a measurable target is approved;
everything else waits for a person, `fn_review_project(id, approve, reviewer, note)`, whose
decision a later regrade never overturns. The formula, how its cut-offs were calibrated,
and the demo results are in `ml/pipeline/README.md`.

Rebuilding: `make datasets` (byte-identical), `make train` (fraud and impact, about 15 s),
`make train-bert` (about 2 h), `make proposals` (BERT's training text; needs a Gemini or
Groq key in `.env`). BERT on text it never trained on: `make eval-human` (the team's
hand-written proposals) and `make eval-unseen` (another LLM's rewrites of the test projects).

## Status

Built and verified:

- Full schema, triggers, transactions, window views, pgvector matching
- 27/27 DB checks pass from a clean `reset`
- Both two-session concurrency tests pass (double funding, and termination against verification)
- FastAPI layer (`api/`) with tests against real Postgres, including a real two-session race
- React frontend (`web/`): six screens, on the API or on an in-browser demo store. `npm test` pins
  the demo's ported matching, window-view and trigger logic to numbers read from this database.
- Synthetic training data: 500 NGOs, 2,000 projects, 2,416 NGO-years of spending, and 2,000
  LLM-written proposals, each checked fact by fact
- Isolation Forest, XGBoost and three BERT readers, evaluated on held-out NGOs
- Risk grade and manual review in SQL, and a scoring pipeline (`make score`) that writes real
  model output into the database; an end-to-end test runs it against a throwaway database
- GitHub Actions CI (`.github/workflows/ci.yml`): the database, API and ML tests against a real
  pgvector Postgres, and the frontend's tests and build, on every push
- Live submission: an NGO submits a proposal in its portal and the models score it in a few
  seconds; a reviewer approves or rejects what the grade flagged; a company edits its funding
  criteria on Find projects. The first submission after `make api` also loads the models. The in-browser demo
  can review, but scoring and embedding need the API, where the Python models run.

Still to do:

- The unseen-writer test: add `GROQ_API_KEY` to `.env`, then `make proposals-unseen` and
  `make eval-unseen` (Groq rewrites the test projects; BERT never trained on Groq's text)
- The team's 40 hand-written proposals from `ml/datasets/human_test/fact_sheets.md`, then
  `make eval-human`
- Docker images for the API and frontend (Postgres already runs in Docker, and CI uses it)

The extraction, impact, fraud and risk-grade rows in `db/seed.sql` are hand-written
placeholders, and its embeddings synthetic topic vectors, so the database tests and the
browser demo stay deterministic. `make score` replaces them all with real model output.
