# Is everything working?

## One command

```bash
make verify            # everything, about 2 minutes
make verify QUICK=1    # only the layer tests, about 1 minute; leaves your demo data alone
```

It needs Docker running (`make up`). It does not need `make api` or `make web`: the stages
that use a server start their own on spare ports. A healthy run ends like this:

```
Layer tests: each part on its own
  ✓ Database: triggers, funding rules, races, window functions, grading  31 passed  (8s)
  ✓ ML: synthetic world, fraud, impact, BERT readers, scoring pipeline  173 passed  (31s)
  ✓ API: every route, against a throwaway copy of the database  89 passed  (23s)
  ✓ Web: unit tests, type check, production build  74 passed | 13 skipped  (1s)

End to end: the product, as the demo uses it
  ✓ Offline engine: the browser's copy of the rules equals the real API  13 passed  (2s)
  ✓ Demo check: API workflow, every page, browser journey, clean reset  42 of 42 checks  (71s)

Everything passed in 2m 19s. The demo data is clean and scored.
```

The 13 skipped web tests are the offline-engine tests; they run in the end-to-end stage,
where a fresh database is available. Every stage writes its full log to
`demo-check/verify/`.

## What each stage proves

| Stage | Run it alone | What it checks |
|---|---|---|
| Preflight | `make verify` | Docker, the Postgres container, all 8 migrations applied, demo data scored, the Python packages, the trained models, the frontend packages, Google Chrome. Each failure prints its fix. |
| Database (31) | `make test-db` | On a throwaway database built from the migrations and the seed: phases and milestones are created by trigger; verifying releases money and failing holds it; double funding is refused by the function, the trigger and the unique index, each on its own, and by two real concurrent sessions; a refused commitment leaves no partial rows; the ledger cannot be edited or deleted; the window-function views; pgvector matching; terminating refunds what was not released, including against a racing verification; the risk grade and the reviewer's decision; the promised gain behind the progress bar, and that storing a rating never moves money. |
| ML (173) | `make test-ml` | The synthetic world is deterministic; the fraud, impact and BERT pipelines; the proposal generator and its fact checker; the scoring pipeline writing real model output into a throwaway database; the progress rater (the bar, the 1-5 rules, the caps no model can talk past, reading Gemini's answer). |
| API (89) | `make test-api` | Every route, each against its own copy of the database, including a real two-session race, and updates rated after they are saved (a failing rater loses nothing). |
| Web (74) | `make test-web` | The browser's port of the database rules, the claim and milestone rules, the reworded exclusion reasons; then the type check and the production build. |
| Offline engine (13) | `make test-parity` | The offline fallback gives the same answers as the real API on a freshly seeded database, for reads and for a scripted sequence of writes. |
| Demo check (42) | `make demo-check` | Rebuilds and scores the database with the models; runs the deck's workflow through the API; renders all 15 portal pages in Chrome; then the browser journey (below); then resets to a clean, scored demo. |

**The browser journey** (`web/e2e/journey.mjs`, 33 steps) is the product used the way people
would use it: each party in its own browser, clicking the real pages. An NGO submits the sample
proposal and sees its grade but not the fraud screen. The reviewer reads why a project was held
back, approves one and rejects another. A company funds the approved project and cannot fund it
twice. The NGO submits evidence with its own words, the reviewer reads them beside the rating, and verifying releases the money. The next
milestone fails, the NGO sees the payment held, and the company ends the commitment for a
refund. Then the safeguards, a monthly impact report, an NGO trying to open another NGO's
project, missing projects, and a phone-width pass over every page. Any console error, page error
or server error fails it. With `make api` and `make web` already running, `make ui-check` runs
just the journey (about 40 seconds). Its screenshots are in `demo-check/journey/`.

## Does it touch the demo data?

- `make verify QUICK=1` and the layer tests: **no.** Each layer builds its own throwaway
  database from the files (`make test-db` uses `csr_dbtest` and drops it afterwards), so the
  tests pass or fail the same whatever has been clicked in the demo.
- `make verify`, `make demo-check`, `make ui-check`: **yes.** They replace the demo data and
  leave a clean, scored demo.
- `make test-parity` on its own: replaces the demo data with the **unscored** seed. Run
  `make score`, or Reset demo data in the review console, afterwards.

To keep what is in the database first: `docker exec csr_db pg_dump -U csr -Fc csr_exchange > backup.dump`.

## When something fails

Fix the first failure first: later stages often fail because of it.

| You see | Do |
|---|---|
| ✗ Docker is running / Postgres container | Start Docker Desktop, then `make up`. |
| ✗ Schema has all 8 migrations | `make demo` rebuilds the database from `db/migrations` and seeds it. |
| ✗ Trained models | `make train train-bert` (BERT takes about an hour on an M-series Mac). |
| ✗ Frontend packages | `cd web && npm install`. |
| ✗ Google Chrome | Install Google Chrome; the page checks and the browser journey drive it. |
| A stage fails | Read the lines printed under it, then the full log in `demo-check/verify/`, and rerun just that stage with the command shown. |
| A browser journey step fails | The step's name says what a user would have seen go wrong. Screenshots of every step are in `demo-check/journey/`. |
| Demo check says a port is in use | Another check is still running (ports 8021, 4321 and 8022). Wait for it, or stop it. |

## By hand: ten minutes before a review

The automated checks prove the behaviour. A person still has to judge whether it reads and
looks right. With `make api` and `make web` running, open http://localhost:5173 and check:

1. **Sign in.** Three accounts and the woven panel on the right.
2. **NGO, Gramin Shiksha Trust.** New proposal, then **Fill in a sample proposal**, then
   **Submit proposal**. Within seconds it opens the result: grade B, approved. Under *What the
   reader picked out*: 2,400 beneficiaries, Gaya, 41% to 55%. No fraud score anywhere.
3. **Reviewer.** The queue lists the held-back proposals with a reason each. *Sanitation block
   construction* shows the spending table with the jumps highlighted. Approve *Maternal health
   outreach* with a note; the page then says *Why the scoring held it back* and that a reviewer
   approved it.
4. **Company, Kalpataru Motors.** Find projects ranks *Maternal health outreach*. Fund it and
   commit; Overview's budget cloth now has a locked band for it.
5. **NGO, Arogya Health Mission.** *Needs you now* asks for phase 1 evidence. Submit it; the phase
   says *Evidence submitted*.
6. **Reviewer.** *Evidence to verify*: Verify. The company's Funding page shows phase 1 released.
7. **Safeguards.** Race two sessions: exactly one commitment. Try each rule: each is refused.
8. **Phone.** Narrow the window to phone width on any page: nothing scrolls sideways.
9. **Offline.** Stop `make api` and reload: the sidebar says *Offline demo data* and the pages
   still work (submitting a proposal is greyed out with a reason). Start `make api` again.

Finish with **Reset demo data** in the review console.

## Not covered

- Keyboard-only use and screen readers: the pages have labels and focus outlines, but no test
  drives them that way.
- Sign-in security: there is none yet. The demo accounts have no passwords and the API has no
  authentication.
- Model quality on hand-written proposals (`make eval-human`, needs the team's 40 proposals) and
  on another model's writing (`make eval-unseen`, needs `GROQ_API_KEY`).
- Load: nothing measures many users at once.
- Gemini itself: the checks use the rules rater so they repeat exactly and never need the network. `make ui-check` on a live `make api` uses Gemini when the key is set.
