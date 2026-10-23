# Running the demo

## Before you present (5 minutes)

```bash
make up            # Postgres with pgvector (Docker)
make demo-check    # about 1 min: runs the workflow, clicks through every portal in Chrome, leaves a clean scored demo
make api           # terminal 1: the API on http://localhost:8000
make web           # terminal 2: the frontend on http://localhost:5173
```

`make demo-check` must end with **all checks passed**. It needs the trained models in
`ml/artifacts/` (`make train train-bert` once) and Google Chrome. Its browser journey
(`web/e2e/journey.mjs`) plays every party through the real pages: submit, review, fund,
evidence, verify, fail and refund, safeguards, impact, and a phone-width pass. With `make api`
and `make web` already running, `make ui-check` runs just that journey (about 40 s); it resets
the demo data at the start and the end.

Then open http://localhost:5173, continue as **Exchange reviewer** and click **Reset demo
data** at the bottom of the sidebar once. It rebuilds the demo, rescores it with the models,
and loads them into the API (about 20 s), so the live submission later answers in a few
seconds. The sidebar must say **Connected**; if it says *Offline demo data*, the API is not
running.

Open one browser tab per party so you never have to sign out mid-demo (each portal has its
own address):

| Tab | Address | Signed in as |
|---|---|---|
| NGO | http://localhost:5173/ngo/2 | Gramin Shiksha Trust |
| Reviewer | http://localhost:5173/review | Exchange reviewer |
| Company | http://localhost:5173/company/2 | Kalpataru Motors |
| Second NGO | http://localhost:5173/ngo/3 | Arogya Health Mission |

## The walk-through

Follows the deck: an NGO submits, the models score, a person decides, SQL moves the money.
Each party sees only its own work: NGOs never see fraud scores, companies cannot verify
milestones, and only the reviewer can approve, verify or reset. A tab refreshes after its own
actions; after acting in another tab, reload it.

| # | Portal and page | Do | Say |
|---|---|---|---|
| 1 | **Sign in** (http://localhost:5173) | Show the three accounts. | Three parties, three portals, one database. |
| 2 | **NGO**, New proposal | Click **Fill in a sample proposal** (or paste the text below: title, sector Education, state Bihar, ₹12,00,000, 12 months, 2 phases). **Submit proposal**. | BERT reads it, the Isolation Forest checks the NGO's spending, XGBoost forecasts the impact, `fn_grade_project` decides. The page opens on the result. |
| 3 | **Reviewer**, Queue | Point at *Proposals to decide*. Open **Sanitation block construction**: *Why it is in review* and *Spending check*. | The Isolation Forest caught the NGO's anomalous year: admin 38%, round-number invoices 76%, one vendor 91%. A flag routes it to a person; no model rejects anything. |
| 4 | **Reviewer**, Queue | Open **Maternal health outreach**. Under **Your decision**, note "baseline confirmed with the district office", **Approve**. | The grade sent it to review; a person decided. A later rescore will not overturn that. |
| 5 | **Company**, Overview, then Find projects | Show the budget cloth on Overview. On Find projects, show the ranking and *Not eligible*. **Fund this project** on *Maternal health outreach*, then **Commit**. | pgvector ranks inside Postgres: similarity, expected impact, spending record. Funding is one transaction: money locked, phases and milestones created by trigger. |
| 6 | **Second NGO**, My projects | Reload. Under *Needs you now*, **Submit evidence** for phase 1, then **Submit evidence** on the phase card. | The NGO reports; that moves no money. |
| 7 | **Reviewer**, Queue | Under *Evidence to verify*: **Verify** (money released) or **Fail** (money held). | No milestone proof, no release. A trigger moves the money; no model is near that path. |
| 8 | **Reviewer**, Safeguards | **Race two sessions**. Then **Try it** on each rule. | Two real sessions fund the same project; exactly one wins. The database itself refuses double funding, over-budget commitments and ledger edits. |
| 9 | **Company**, Impact (switch to Meridian at http://localhost:5173/company/1/impact) | Show the chart and the leaderboard. Optional: as Vidya Foundation (http://localhost:5173/ngo/1/projects/1) **Report progress**, then reload Impact. | Window functions recompute the rolling score and the NGO leaderboard on every read. |

To start over at any point: reviewer, **Reset demo data** (rebuilds and rescores in about 20 s).

### The sample proposal in step 2

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
| Sidebar says *Offline demo data* | The API is down: run `make api`, reload the page. |
| A submission says *Not scored* | The models are missing: `make train train-bert`. The proposal is saved as pending; `make score` grades it later. |
| *Cannot reach the server* | `make up` (Postgres), then `make api`. |
| Scores look hand-typed (a note under *Overall score* says so) | Reviewer, **Reset demo data** on the live API, or `make score`. |
| *Submit proposal* is greyed out | The API is not reachable; the offline demo cannot run the models. |

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
