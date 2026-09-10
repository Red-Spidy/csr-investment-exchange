"""Multi-label classification metrics.

Deliberately dependency-free and hand-checkable. These numbers go into the
report, so the arithmetic is tested against worked examples in test_metrics.py
rather than trusted because a library produced it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LabelScore:
    label: int
    support: int   # how many times the label truly occurs
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class MultiLabelReport:
    per_label: list[LabelScore]

    @property
    def micro_f1(self) -> float:
        """Pools every decision. Dominated by frequent labels."""
        tp = sum(s.tp for s in self.per_label)
        fp = sum(s.fp for s in self.per_label)
        fn = sum(s.fn for s in self.per_label)
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / (tp + fn) if (tp + fn) else 0.0
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def macro_f1(self) -> float:
        """Unweighted mean over labels that actually occur. Rare labels count
        as much as common ones -- the honest number for a skewed SDG set."""
        present = [s for s in self.per_label if s.support > 0]
        return sum(s.f1 for s in present) / len(present) if present else 0.0

    @property
    def exact_match_note(self) -> str:
        return f"{len(self.per_label)} labels evaluated"

    def to_markdown(self) -> str:
        lines = [
            "| SDG | Support | Precision | Recall | F1 |",
            "|----:|--------:|----------:|-------:|---:|",
        ]
        for s in sorted(self.per_label, key=lambda x: x.label):
            if s.support == 0 and s.tp == 0 and s.fp == 0:
                continue
            lines.append(
                f"| {s.label} | {s.support} | {s.precision:.3f} | {s.recall:.3f} | {s.f1:.3f} |"
            )
        lines.append("")
        lines.append(f"**Micro-F1: {self.micro_f1:.4f} · Macro-F1: {self.macro_f1:.4f}**")
        return "\n".join(lines)


def evaluate_multilabel(
    gold: list[list[int]],
    pred: list[list[int]],
    labels: range | list[int] = range(1, 18),
) -> MultiLabelReport:
    """Compare predicted label sets against gold label sets, per label."""
    if len(gold) != len(pred):
        raise ValueError(f"gold has {len(gold)} rows, pred has {len(pred)}")

    gold_sets = [set(g) for g in gold]
    pred_sets = [set(p) for p in pred]

    scores = []
    for label in labels:
        tp = sum(1 for g, p in zip(gold_sets, pred_sets) if label in g and label in p)
        fp = sum(1 for g, p in zip(gold_sets, pred_sets) if label not in g and label in p)
        fn = sum(1 for g, p in zip(gold_sets, pred_sets) if label in g and label not in p)
        support = sum(1 for g in gold_sets if label in g)
        scores.append(LabelScore(label=label, support=support, tp=tp, fp=fp, fn=fn))

    return MultiLabelReport(per_label=scores)


def confusion_pairs(
    gold: list[list[int]], pred: list[list[int]], top_n: int = 10
) -> list[tuple[int, int, int]]:
    """Most common (true label, wrongly predicted label) pairs.

    Tells you WHICH SDGs the classifier conflates -- SDG 3 vs 6 (health vs
    water) and 1 vs 8 (poverty vs decent work) are the usual offenders, and
    that is a more useful report finding than a single F1 number.
    """
    counts: dict[tuple[int, int], int] = {}
    for g, p in zip(gold, pred):
        missed = set(g) - set(p)
        spurious = set(p) - set(g)
        for m in missed:
            for s in spurious:
                counts[(m, s)] = counts.get((m, s), 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return [(a, b, n) for (a, b), n in ranked[:top_n]]
