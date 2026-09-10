# CSR Investment Exchange

AI-scored, SQL-automated matching of corporate CSR budgets to NGO projects.
Companion implementation for the ADV_SQL review deck.

## Quick start

```bash
docker compose up -d          # or: make up
make migrate seed             # schema + demo scenario
make test                     # DB assertions + ML eval checks
make psql                     # poke around
```

Postgres listens on **localhost:5433** (5433, not 5432, to avoid colliding with
a local install).

For the NLP module you also need Python deps and an API key:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # then set ANTHROPIC_API_KEY
```

## Layout

| Path | What it is |
|---|---|
| `db/migrations/` | Schema, triggers, window views, pgvector matching. Applied in filename order. |
| `db/tests/` | Assertion tests. Each `RAISE`s on failure, so a non-zero exit is a real regression. |
| `db/seed.sql` | Deterministic demo scenario. |
| `ml/nlp/` | Claude extraction, embeddings, DB persistence. |
| `ml/eval/` | Metric implementations + their hand-worked tests. |
| `ml/impact/`, `ml/fraud/` | XGBoost / Isolation Forest (not yet built). |
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

## The NLP module

One Claude call per proposal does field extraction **and** SDG classification —
they read the same text, so splitting them doubles cost for nothing. Nothing is
fine-tuned.

- `ml/nlp/schemas.py` — the Pydantic schema Claude fills. Almost every field is
  `| None`: the prompt instructs the model to emit null for anything the
  proposal does not state, because a hallucinated beneficiary count flows into
  the impact forecast and then into a funding decision.
- `ml/nlp/prompts.py` — system prompt + few-shot examples, versioned. One
  example is deliberately a near-empty proposal, to teach abstention.
- `ml/nlp/extract.py` — `messages.parse()` with cache breakpoints on the stable
  prefix, a Batch API path for the corpus run (half price), and a rule-based
  fallback for when the API is unreachable.
- `ml/nlp/embed.py` — MiniLM (384-dim) over *canonicalised* text, not the raw
  proposal. Both sides of the match are canonicalised the same way.

**The LLM is never in the fund-release path.** It produces evidence; a human
sets a verification flag; a SQL trigger moves money.

### Evaluation without training

You do not need to train a model to evaluate one — you need a labelled test set.

- `ml/eval/metrics.py` — per-SDG precision/recall/F1, micro/macro-F1, confusion
  pairs. Run against the OSDG Community Dataset as a held-out test set.
- `ml/eval/extraction_eval.py` — field accuracy and, the headline number,
  **hallucination rate**: how often the model filled a field the proposal never
  stated. Abstention is scored separately from error, because for this pipeline
  they have very different costs.

Both metric modules have hand-worked tests (`test_metrics.py`,
`test_extraction_eval.py`) where every expected value is computed by hand in a
comment. These numbers go in the report, so the arithmetic is verified rather
than trusted.

## Status

Built and verified:

- Full schema, triggers, transactions, window views, pgvector matching
- 10/10 DB assertions pass, from a clean `reset` and against real embeddings
- Two-session concurrency test passes
- Embeddings + DB persistence, verified end-to-end against a live database
- Eval metric modules, verified against hand-computed values

Not yet built: XGBoost impact model, Isolation Forest fraud model, FastAPI
layer, React frontend, corpus generation.

**Not yet verified: the live Claude API call path.** No `ANTHROPIC_API_KEY` was
available in this environment, so `extract_proposal()` has been exercised only
through its fallback branch. Set a key and run one proposal before relying on it.
