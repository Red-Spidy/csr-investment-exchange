"""Structured output schema for NGO proposal extraction.

One Claude call fills this entire model: field extraction AND SDG classification.
They read the same text, so splitting them into two calls doubles cost for nothing.

The `| None` on almost every field is load-bearing. The system prompt instructs
the model to emit null for anything the proposal does not state, because a
hallucinated beneficiary count flows into the impact forecast and from there
into a funding decision. An absent value must stay absent.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TargetMetric(BaseModel):
    name: str | None = Field(None, description="The outcome the project moves, e.g. attendance_rate")
    unit: str | None = Field(None, description="percentage_points, percent_reduction, hectares, ...")
    baseline: float | None = Field(None, description="Stated starting value. Null if not stated.")
    target: float | None = Field(None, description="Stated goal value. Null if not stated.")


class Beneficiaries(BaseModel):
    count: int | None = Field(None, description="Number of people served. Null if not stated.")
    group: str | None = Field(None, description="Who they are, e.g. 'primary school children'")


class Geography(BaseModel):
    state: str | None = None
    district: str | None = None
    rural_urban: str | None = Field(None, description="'rural', 'urban', 'both', or null")


class BudgetLine(BaseModel):
    item: str
    amount: float | None = Field(None, description="Amount in INR. Null if not stated.")


class ProposalExtraction(BaseModel):
    """Everything the NLP module pulls out of one unstructured proposal."""

    goals: list[str] = Field(
        default_factory=list,
        description="Concrete objectives stated in the proposal, in the proposal's own terms.",
    )
    target_metric: TargetMetric | None = None
    beneficiaries: Beneficiaries | None = None
    geography: Geography | None = None
    budget_lines: list[BudgetLine] = Field(default_factory=list)
    duration_months: int | None = None
    sdgs: list[int] = Field(
        default_factory=list,
        description="UN Sustainable Development Goals this project addresses, as integers 1-17.",
    )
    sdg_confidence: dict[str, float] = Field(
        default_factory=dict,
        description="Per-SDG confidence 0-1, keyed by the SDG number as a string.",
    )
    red_flags: list[str] = Field(
        default_factory=list,
        description=(
            "Concrete concerns visible in the proposal text itself: missing budget "
            "detail, unverifiable claims, implausible cost per beneficiary. "
            "Empty list if none. Do not speculate about the NGO's intent."
        ),
    )

    def canonical_text(self, title: str = "") -> str:
        """Build the string that gets embedded for pgvector matching.

        Deliberately NOT the raw proposal. A company rulebook is short and
        structured; a proposal is long and discursive. Embedding the extracted
        structure on both sides compares like with like.
        """
        parts: list[str] = []
        if title:
            parts.append(title)
        parts.extend(self.goals)
        if self.target_metric and self.target_metric.name:
            parts.append(self.target_metric.name.replace("_", " "))
        if self.beneficiaries and self.beneficiaries.group:
            parts.append(self.beneficiaries.group)
        if self.geography:
            parts.extend(p for p in (self.geography.state, self.geography.district) if p)
            if self.geography.rural_urban:
                parts.append(self.geography.rural_urban)
        parts.extend(f"SDG {n}" for n in sorted(self.sdgs))
        return " | ".join(parts)

    def max_sdg_confidence(self) -> float:
        """Confidence in the primary SDG label. Feeds the composite risk grade."""
        return max(self.sdg_confidence.values(), default=0.0)
