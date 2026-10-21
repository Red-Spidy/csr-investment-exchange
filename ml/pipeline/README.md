# Scoring pipeline and risk grade

`make score` runs the three trained models over every project in the database and
lets SQL decide what happens to each one.

| Step | Model | Writes |
|---|---|---|
| Read the proposal | BERT readers (`ml/nlp`) | `project_extractions`: SDGs and confidences, outcome metric, stated fields, goal sentence, red flags, and a MiniLM embedding of the extracted structure |
| Check the NGO's spending | Isolation Forest (`ml/fraud`) | `fraud_scores` |
| Forecast the impact | XGBoost (`ml/impact`) | `impact_predictions`, in the proposal's own units when it states a baseline and a target |
| Decide | `fn_grade_project()` (`db/migrations/008_risk_grade.sql`) | `risk_grades`, and the project's status |

Company rulebooks are embedded with the same MiniLM model (`all-MiniLM-L6-v2`, 384
dimensions), so `fn_match_projects` compares like with like. The seed's synthetic topic
vectors are replaced.

The models only write evidence. The grade, the approval and every later money movement
happen in SQL.

## The grade

```
composite = 0.45 * impact          predicted share of the claim delivered
          + 0.30 * (1 - fraud_risk) fraud_risk = clamp((anomaly_percentile - 0.80) / 0.20, 0, 1)
          + 0.15 * sdg_confidence  best SDG confidence from BERT
          + 0.10 * track_record    share of the NGO's decided milestones that passed; 0.5 if none
```

| Grade | Composite |
|---|---|
| A | ≥ 0.84 |
| B | ≥ 0.77 |
| C | ≥ 0.69 |
| D | below |

**Approved** only with grade A or B, no fraud flag, and a measurable target. Everything
else is `flagged` for a person, who settles it with
`fn_review_project(project_id, approve, reviewer, note)`. A review decision stands: running
the pipeline again updates the evidence but never overturns it. A project that already has
money committed is never re-graded into a different status, because its status belongs to
the milestone triggers. Nothing is rejected automatically.

### Why fraud is a risk, not the raw percentile

The anomaly score is a percentile against training NGOs, so an ordinary NGO sits anywhere
between 0 and 0.8. Used raw, that spread swamped the impact signal: grades A and B
delivered the same (0.672 and 0.673). The clamped risk is zero for the 80% most ordinary
NGOs and reaches 0.5 at the review flag.

| Fraud term in the composite | Rank correlation with delivery, val | test |
|---|---:|---:|
| percentile as is | 0.417 | 0.268 |
| above median | 0.441 | 0.327 |
| **top 20% (used)** | **0.557** | **0.425** |

### Calibration

Cut-offs were set on the synthetic **validation** split (A = top 30%, B next 30%, C next
25%) and checked once on **test**, with all three trained models scoring the proposals:

| Grade | Test projects | Share of the claim actually delivered | From fraudulent NGOs |
|---|---:|---:|---:|
| A | 44 | 0.78 | 0 |
| B | 82 | 0.63 | 0 |
| C | 45 | 0.58 | 0 |
| D | 30 | 0.46 | 11 |

Approved projects delivered 0.69 of their claims; projects sent to review, 0.53. None of
the 11 projects of fraudulent NGOs was approved.

## On the demo scenario

The eight seeded proposals are hand-written (not generated), so they are also a first look
at BERT on text it did not train on. `make demo && make score`:

| Project | Grade | Outcome | Forecast |
|---|---|---|---|
| 1 Barmer attendance | B | funded already, status kept | +4.16 points of attendance [2.65, 6.86] |
| 2 Gaya digital classrooms | B | approved | outcome score 0.68 (baseline not read) |
| 3 Vidarbha maternal health | C | review | outcome score 0.61 (baseline not read) |
| 4 Jaisalmer handpumps | D | review: fraud flag | outcome score 0.53 |
| 5 Western Ghats reforestation | D | review | +131 hectares [94, 271] |
| 6 Bargarh weavers | C | review | +13.5% income [8.0, 20.3] |
| 7 Library expansion | A | review: no measurable target | outcome score 0.74 |
| 8 Sanitation blocks | D | review: fraud flag | outcome score 0.64 |

The Isolation Forest flags NGO 4, whose FY23-24 spending in the seed carries the planted
anomaly, so both its projects go to review with no hand-written score involved.

## Known limitations

- **BERT reads hand-written text worse than generated text.** On the demo proposals it
  mistook counts of things for beneficiaries ("80,000 saplings", "12 schools", "60 toilet
  blocks") and missed baselines phrased unusually ("only 54% of pregnant women
  complete..."). The cause is the first corpus: the checker rejected every number that was
  not a fact, so every number BERT trained on *was* one. Prompt `p4` adds unlabelled
  context counts (villages, schools, saplings) to 71% of fact sheets. The next generated
  batch and a retrain should fix the beneficiary confusion; the team-written test set
  (`ml/datasets/human_test/`) is where to measure it.
- **The grade is calibrated on synthetic outcomes.** Its weights come from the deck; its
  cut-offs from the synthetic world. Treat it as a demonstration of the mechanism, not a
  validated credit model.
- **The track record starts neutral.** It only moves once an NGO's milestones are verified
  or failed in this database.
