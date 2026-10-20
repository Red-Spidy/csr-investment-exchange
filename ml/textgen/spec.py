"""The facts one generated proposal must state -- and the ones it must not.

A spec is built from the synthetic world, so every label BERT later trains on
(SDGs, beneficiary count, baseline, target, amount, ...) is known before the
text exists. The LLM only writes prose around facts it is given.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProposalSpec:
    project_id: int
    ngo_name: str
    founded: int
    sector: str
    title: str
    state: str
    district: str
    activities: tuple[str, ...]
    beneficiary_group: str
    beneficiaries: int | None            # None: the proposal must not state it
    metric_label: str
    metric_unit: str
    baseline: float | None               # None: the proposal must not state it
    target: float
    zero_baseline: bool                  # metrics that start from nothing, e.g. hectares planted
    amount: int
    duration_months: int
    num_phases: int
    budget_lines: tuple[tuple[str, int], ...] | None   # None: no breakdown
    omitted: dict[str, float]            # true values that must NOT appear in the text
    style: str
    length_words: int
    metric_direction: str = "increase"   # 'increase' | 'decrease'
