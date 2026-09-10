"""Hand-worked checks on the metric arithmetic.

Every expected number below is computed by hand in the comment above it. These
figures go into the project report, so the arithmetic gets verified rather than
assumed.  Run: .venv/bin/python ml/eval/test_metrics.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from metrics import confusion_pairs, evaluate_multilabel

FAILURES = []


def check(name, actual, expected, tol=1e-6):
    ok = abs(actual - expected) < tol if isinstance(expected, float) else actual == expected
    if not ok:
        FAILURES.append(f"{name}: got {actual!r}, expected {expected!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {actual}")


# ---------------------------------------------------------------- fixture
# 5 documents, labels restricted to SDG 3, 4, 6.
#
# doc  gold      pred        SDG3        SDG4        SDG6
#  1   {4}       {4}         -           TP          -
#  2   {4}       {4,6}       -           TP          FP
#  3   {3}       {6}         FN          -           FP
#  4   {6}       {6}         -           -           TP
#  5   {3,6}     {3}         TP          -           FN
#
# SDG3: tp=1 fp=0 fn=1 support=2 -> P=1/1=1.0000 R=1/2=0.5000 F1=2(1)(.5)/1.5   =0.6667
# SDG4: tp=2 fp=0 fn=0 support=2 -> P=1.0000     R=1.0000     F1              =1.0000
# SDG6: tp=1 fp=2 fn=1 support=2 -> P=1/3=0.3333 R=1/2=0.5000 F1=2(.3333)(.5)/.8333=0.4000
GOLD = [[4], [4], [3], [6], [3, 6]]
PRED = [[4], [4, 6], [6], [6], [3]]

print("per-label")
rep = evaluate_multilabel(GOLD, PRED, labels=[3, 4, 6])
by_label = {s.label: s for s in rep.per_label}

check("SDG3 precision", by_label[3].precision, 1.0)
check("SDG3 recall", by_label[3].recall, 0.5)
check("SDG3 f1", by_label[3].f1, 2 / 3)
check("SDG3 support", by_label[3].support, 2)

check("SDG4 f1", by_label[4].f1, 1.0)
check("SDG4 support", by_label[4].support, 2)

check("SDG6 precision", by_label[6].precision, 1 / 3)
check("SDG6 recall", by_label[6].recall, 0.5)
check("SDG6 f1", by_label[6].f1, 0.4)
check("SDG6 support", by_label[6].support, 2)

print("\naggregate")
# micro: TP=4 FP=2 FN=2 -> P=4/6 R=4/6 F1=4/6
check("micro_f1", rep.micro_f1, 4 / 6)
# macro: (0.666667 + 1.0 + 0.4)/3 = 0.688889
check("macro_f1", rep.macro_f1, (2 / 3 + 1.0 + 0.4) / 3)

print("\nedge cases")
# a label that never occurs and is never predicted must not drag macro down
rep2 = evaluate_multilabel([[4]], [[4]], labels=[4, 13])
check("macro ignores absent label", rep2.macro_f1, 1.0)

# a label predicted but never true: precision 0, and it DOES count against micro
rep3 = evaluate_multilabel([[4]], [[4, 13]], labels=[4, 13])
check("micro penalises false positive", rep3.micro_f1, 2 * 1 * 0.5 / 1.5)  # P=1/2,R=1/1
check("macro ignores never-true label", rep3.macro_f1, 1.0)

# perfect and empty
check("all correct -> 1.0", evaluate_multilabel([[1], [2]], [[1], [2]], [1, 2]).micro_f1, 1.0)
check("all wrong -> 0.0", evaluate_multilabel([[1], [1]], [[2], [2]], [1, 2]).micro_f1, 0.0)

print("\nconfusion pairs")
# doc3 missed 3, spuriously predicted 6 -> (3,6) once
# doc5 missed 6, spuriously predicted nothing -> no pair
# doc2 missed nothing -> no pair
pairs = confusion_pairs(GOLD, PRED)
check("top confusion pair is (3 -> 6)", pairs[0][:2], (3, 6))

print("\nmarkdown table renders")
table = rep.to_markdown()
assert "Micro-F1" in table and "| 3 |" in table
print(table)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all metric checks passed")
