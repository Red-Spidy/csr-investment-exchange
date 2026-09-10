"""Field-level evaluation of proposal extraction against gold annotations.

The headline number here is the HALLUCINATION RATE: how often the model filled
in a field the proposal never stated. For this pipeline that is the failure that
matters -- a wrong-but-present beneficiary count or baseline flows into the
impact forecast and from there into a funding decision, whereas a null routes
the project to human review and costs nothing but time.

Field outcomes:
  correct       gold and prediction agree (both null, or equal values)
  hallucinated  gold is null, model produced a value      <- the dangerous one
  missed        gold has a value, model produced null     <- conservative, safe
  wrong         both present, values disagree
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# Dotted paths into the extraction object that carry a factual claim.
SCALAR_FIELDS = [
    "target_metric.name",
    "target_metric.unit",
    "target_metric.baseline",
    "target_metric.target",
    "beneficiaries.count",
    "beneficiaries.group",
    "geography.state",
    "geography.district",
    "geography.rural_urban",
    "duration_months",
]

NUMERIC_FIELDS = {
    "target_metric.baseline",
    "target_metric.target",
    "beneficiaries.count",
    "duration_months",
}


def dig(obj: dict | None, path: str):
    """Walk a dotted path, treating a missing branch as null."""
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _equal(a, b, numeric: bool) -> bool:
    if numeric:
        try:
            return abs(float(a) - float(b)) < 1e-6
        except (TypeError, ValueError):
            return False
    return str(a).strip().lower() == str(b).strip().lower()


@dataclass
class ExtractionReport:
    outcomes: Counter = field(default_factory=Counter)
    per_field: dict[str, Counter] = field(default_factory=dict)
    n_docs: int = 0

    @property
    def total(self) -> int:
        return sum(self.outcomes.values())

    @property
    def hallucination_rate(self) -> float:
        """Of the fields the proposal left unstated, how many did the model fill?"""
        eligible = self.outcomes["hallucinated"] + self.outcomes["correct_null"]
        return self.outcomes["hallucinated"] / eligible if eligible else 0.0

    @property
    def accuracy(self) -> float:
        correct = self.outcomes["correct"] + self.outcomes["correct_null"]
        return correct / self.total if self.total else 0.0

    @property
    def recall_on_stated(self) -> float:
        """Of the fields the proposal DID state, how many were recovered correctly?"""
        stated = self.outcomes["correct"] + self.outcomes["missed"] + self.outcomes["wrong"]
        return self.outcomes["correct"] / stated if stated else 0.0

    def to_markdown(self) -> str:
        lines = [
            f"Documents evaluated: **{self.n_docs}** · field decisions: **{self.total}**",
            "",
            "| Outcome | Count | Share |",
            "|---|---:|---:|",
        ]
        for key in ("correct", "correct_null", "missed", "wrong", "hallucinated"):
            n = self.outcomes[key]
            lines.append(f"| {key} | {n} | {n / self.total:.1%} |" if self.total else f"| {key} | {n} | - |")
        lines += [
            "",
            f"**Hallucination rate: {self.hallucination_rate:.2%}** "
            f"(fields invented where the proposal said nothing)",
            f"**Accuracy: {self.accuracy:.2%}** · "
            f"**Recall on stated fields: {self.recall_on_stated:.2%}**",
            "",
            "| Field | correct | correct_null | missed | wrong | hallucinated |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for name in SCALAR_FIELDS:
            c = self.per_field.get(name, Counter())
            lines.append(
                f"| `{name}` | {c['correct']} | {c['correct_null']} | "
                f"{c['missed']} | {c['wrong']} | {c['hallucinated']} |"
            )
        return "\n".join(lines)


def evaluate_extractions(gold: list[dict], pred: list[dict]) -> ExtractionReport:
    """gold/pred are lists of extraction dicts, aligned by index."""
    if len(gold) != len(pred):
        raise ValueError(f"gold has {len(gold)} docs, pred has {len(pred)}")

    report = ExtractionReport(n_docs=len(gold))
    for name in SCALAR_FIELDS:
        report.per_field[name] = Counter()

    for g_doc, p_doc in zip(gold, pred):
        for name in SCALAR_FIELDS:
            g, p = dig(g_doc, name), dig(p_doc, name)
            numeric = name in NUMERIC_FIELDS

            if g is None and p is None:
                outcome = "correct_null"
            elif g is None:
                outcome = "hallucinated"
            elif p is None:
                outcome = "missed"
            elif _equal(g, p, numeric):
                outcome = "correct"
            else:
                outcome = "wrong"

            report.outcomes[outcome] += 1
            report.per_field[name][outcome] += 1

    return report


def agreement(run_a: list[dict], run_b: list[dict]) -> float:
    """Field-level agreement between two runs over the same inputs.

    Sampling parameters are not available on the current models, so determinism
    is not promised -- this measures the consistency actually observed.
    """
    if len(run_a) != len(run_b):
        raise ValueError("runs must cover the same documents")
    same = total = 0
    for a_doc, b_doc in zip(run_a, run_b):
        for name in SCALAR_FIELDS:
            a, b = dig(a_doc, name), dig(b_doc, name)
            total += 1
            if a is None and b is None:
                same += 1
            elif a is not None and b is not None and _equal(a, b, name in NUMERIC_FIELDS):
                same += 1
    return same / total if total else 0.0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: extraction_eval.py <gold.json> <pred.json>")
        raise SystemExit(2)
    gold = json.loads(Path(sys.argv[1]).read_text())
    pred = json.loads(Path(sys.argv[2]).read_text())
    print(evaluate_extractions(gold, pred).to_markdown())
