# Running the demo

## Before you present (5 minutes)

```bash
make up            # Postgres with pgvector (Docker)
make demo-check    # about 30 s: runs the whole workflow, renders every page, leaves a clean scored demo
make api           # terminal 1: the API on http://localhost:8000
make web           # terminal 2: the frontend on http://localhost:5173
```

`make demo-check` must end with **all checks passed**. It needs the trained models in
`ml/artifacts/` (`make train train-bert` once) and Google Chrome.

Then open http://localhost:5173 and click **Reset database** in the sidebar once. It
rebuilds the demo, rescores it with the models, and loads them into the API (about 20 s),
so the live submission later answers in a few seconds. The sidebar must say **Live
database**; if it says *Demo data*, the API is not running.

## The walk-through

Follows the deck: an NGO submits, the models score, a person decides, SQL moves the money.

| # | Page | Do | Say |
|---|---|---|---|
| 1 | **Exchange** | Point at the pipeline: scored → approved → funded → closed, and *Held back for review*. | Every proposal passes the models before it can get money. |
| 2 | **Projects** | Click **Submit a proposal**. Paste the proposal below, NGO *Gramin Shiksha Trust*, sector Education, state Bihar, ₹12,00,000, 12 months, 2 phases. Submit. | BERT reads it, the Isolation Forest checks the NGO's spending, XGBoost forecasts the impact, `fn_grade_project` decides. The receipt says what each one found. |
| 3 | **Projects** → *Sanitation block construction* | Show *Why it was held back* and the spending table. | The Isolation Forest caught the NGO's anomalous year: admin 38%, round-number invoices 76%, one vendor 91%. A flag routes it to a person; nothing is rejected by a model. |
| 4 | **Projects** → *Maternal health outreach* | Under **Your decision**, note "baseline confirmed with the district office", **Approve**. | The grade sent it to review; a person decided. A later rescore will not overturn that. |
| 5 | **Matching**, company *Kalpataru Motors* (sidebar) | Show the ranking and *Left out, and why*. **Fund this project** on *Maternal health outreach*. | pgvector ranks inside Postgres: similarity, predicted impact, trust. Funding is one transaction: money locked, phases and milestones created by trigger. |
| 6 | **Safeguards** | **Race two sessions**. Then **Try it** on each rule. | Two real sessions fund the same project; exactly one wins. The database itself refuses double funding, over-budget commitments and ledger edits. |
| 7 | **Funds** | On phase 2: **Submit evidence as the NGO**, then **Verify** → money released. Or **Fail** → money held. | No milestone proof, no release. A trigger moves the money; no model is near that path. |
| 8 | **Impact** | **Report another month**. | Window functions recompute the rolling ESG score and the NGO leaderboard on read. |

To start over at any point: **Reset database** (rebuilds and rescores in about 20 s).

### A proposal to paste in step 2

> Gramin Shiksha Trust will run after-school science clubs for 2,400 adolescent girls in 30
> government schools of Gaya district, Bihar. The average science score of these girls is
> 41% today; with weekly lab sessions, scholarships for science kits and teacher training,
> we aim to raise it from 41% to 55% within 12 months. We request Rs 12 lakh.

Expect grade B, approved. BERT reads SDGs 4 and 5, 2,400 beneficiaries, Gaya, 12 months,
₹12 lakh and the claim 41% → 55%; XGBoost forecasts about +9 points of the 14 promised
(80% interval roughly +5 to +13).

## If something goes wrong

| You see | Do |
|---|---|
| Sidebar says *Demo data* | The API is down: run `make api`, reload the page. |
| A submission says *Not scored* | The models are missing: `make train train-bert`. The proposal is saved as pending; `make score` grades it later. |
| *Lost contact with the API* | `make up` (Postgres), then `make api`. |
| Scores look hand-typed (a note under *Overall score* says so) | **Reset database** on the live API, or `make score`. |

## Honest answers for the panel

- **Is the data real?** The training data is synthetic, anchored to real figures: CSR spend
  by sector (FY24) and World Bank IEG outcome ratings. The data card says exactly how it
  was made: `ml/datasets/README.md`.
- **How good is BERT?** 99% on generated test proposals, from NGOs it never saw. Weaker on
  hand-written text: it misses baselines phrased unusually. The team-written test set
  measures that (`make eval-human`).
- **Why is impact R² only 0.25?** Project outcomes are mostly luck and local conditions. An
  oracle that sees the hidden traits reaches 0.35, so the model gets about 70% of what is
  learnable.
