"""Hand-worked checks on the extraction metrics."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from extraction_eval import SCALAR_FIELDS, agreement, evaluate_extractions

FAILURES = []
def check(name, actual, expected, tol=1e-9):
    ok = abs(actual - expected) < tol if isinstance(expected, float) else actual == expected
    if not ok: FAILURES.append(f"{name}: got {actual!r}, expected {expected!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {actual}")

# 10 scalar fields are scored per document (see SCALAR_FIELDS).
check("scalar field count", len(SCALAR_FIELDS), 10)

# --- doc 1: proposal states everything; model recovers it exactly -> 10 correct
full = {
    "target_metric": {"name": "attendance_rate", "unit": "percentage_points",
                      "baseline": 61.0, "target": 69.0},
    "beneficiaries": {"count": 11000, "group": "primary school children"},
    "geography": {"state": "Rajasthan", "district": "Barmer", "rural_urban": "rural"},
    "duration_months": 12,
}
rep = evaluate_extractions([full], [full])
print("\nidentical documents")
check("all 10 correct", rep.outcomes["correct"], 10)
check("accuracy 1.0", rep.accuracy, 1.0)
check("hallucination rate 0.0", rep.hallucination_rate, 0.0)
check("recall on stated 1.0", rep.recall_on_stated, 1.0)

# --- doc 2: proposal states NOTHING. Gold is all-null.
# Model invents baseline and beneficiaries.count -> 2 hallucinated, 8 correct_null
empty_gold = {"target_metric": None, "beneficiaries": None,
              "geography": None, "duration_months": None}
inventive = {"target_metric": {"name": None, "unit": None, "baseline": 55.0, "target": None},
             "beneficiaries": {"count": 5000, "group": None},
             "geography": None, "duration_months": None}
print("\nmodel invents two fields the proposal never stated")
rep2 = evaluate_extractions([empty_gold], [inventive])
check("hallucinated = 2", rep2.outcomes["hallucinated"], 2)
check("correct_null = 8", rep2.outcomes["correct_null"], 8)
# hallucination rate = 2 / (2 + 8) = 0.20
check("hallucination rate 0.20", rep2.hallucination_rate, 0.2)
check("accuracy 0.80", rep2.accuracy, 0.8)
# nothing was stated, so recall-on-stated is undefined -> 0.0
check("recall on stated 0.0 (nothing stated)", rep2.recall_on_stated, 0.0)

# --- doc 3: abstention is NOT punished as hallucination
print("\nmodel abstains where the proposal did state a value")
rep3 = evaluate_extractions([full], [empty_gold])
check("missed = 10", rep3.outcomes["missed"], 10)
check("hallucinated = 0", rep3.outcomes["hallucinated"], 0)
check("hallucination rate 0.0 when abstaining", rep3.hallucination_rate, 0.0)
check("recall on stated 0.0", rep3.recall_on_stated, 0.0)

# --- doc 4: present but wrong is 'wrong', not 'hallucinated'
print("\nmodel gives a present-but-incorrect value")
wrong = {**full, "duration_months": 9}
rep4 = evaluate_extractions([full], [wrong])
check("wrong = 1", rep4.outcomes["wrong"], 1)
check("correct = 9", rep4.outcomes["correct"], 9)
check("hallucinated = 0", rep4.outcomes["hallucinated"], 0)
# recall on stated = 9 / (9 + 0 + 1) = 0.9
check("recall on stated 0.9", rep4.recall_on_stated, 0.9)

# --- numeric tolerance and string case-insensitivity
print("\nvalue comparison")
check("61 == 61.0", evaluate_extractions(
    [{"target_metric": {"baseline": 61}}], [{"target_metric": {"baseline": 61.0}}]
).outcomes["wrong"], 0)
check("'Rajasthan' == 'rajasthan '", evaluate_extractions(
    [{"geography": {"state": "Rajasthan"}}], [{"geography": {"state": "rajasthan "}}]
).outcomes["wrong"], 0)

# --- consistency between two runs
print("\nrun-to-run agreement")
check("identical runs -> 1.0", agreement([full], [full]), 1.0)
# 9 of 10 fields agree
check("one field differs -> 0.9", agreement([full], [wrong]), 0.9)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S):")
    for f in FAILURES: print("  -", f)
    sys.exit(1)
print("all extraction-eval checks passed")
