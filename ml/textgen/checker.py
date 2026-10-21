"""Verify an LLM-written proposal against its spec.

A proposal is accepted only if it states every fact it was given with the
exact numbers, describes every activity (the SDG labels come from them),
leaves out what it was told to leave out, invents no numbers, and does not
name SDGs outright. Accepted proposals come with character spans for each
fact -- the token labels BERT's field extractor trains on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from synth.catalog import ACTIVITY_KEYWORDS
from textgen.spec import ProposalSpec

_MULTIPLIER = {"lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
               "crore": 10_000_000, "crores": 10_000_000, "million": 1_000_000, "mn": 1_000_000}
_NUMBER = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{2,3})+|\d+)(\.\d+)?(\s*(?:lakhs?|lacs?|crores?|million|mn)\b)?",
    re.IGNORECASE,
)
_SDG = re.compile(r"\bsdgs?\b|sustainable development goal", re.IGNORECASE)
# Citations of the CSR law itself. Real proposals make them, and their numbers
# are neither facts about the project nor inventions.
_LAW = re.compile(r"\bsection\s+135\b|\bcompanies\s+act,?\s+2013\b", re.IGNORECASE)
SMALL_INTEGERS = {1, 2, 3, 4, 5}   # list numbering, "phase 2": not facts


@dataclass(frozen=True)
class Number:
    value: float
    start: int
    end: int


@dataclass
class CheckResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    spans: dict[str, tuple[int, int]] = field(default_factory=dict)


def find_numbers(text: str) -> list[Number]:
    """Every number in the text, with lakh/crore/million applied."""
    found = []
    for m in _NUMBER.finditer(text):
        # Decimal, not float: 9.2 lakh must be exactly 920000, not 919999.99...
        value = Decimal(m.group(1).replace(",", "") + (m.group(2) or ""))
        if m.group(3):
            value *= _MULTIPLIER[m.group(3).strip().lower()]
        found.append(Number(float(value), m.start(), m.end()))
    return found


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-6 * max(1.0, abs(b))


def _activity_described(activity: str, lowered: str) -> bool:
    return any(all(part in lowered for part in alt.split("+")) for alt in ACTIVITY_KEYWORDS[activity])


def _duration_values(months: int) -> list[tuple[float, str]]:
    values = [(float(months), "month")]
    if months % 6 == 0:
        values.append((months / 12, "year"))
    return values


def _is_duration(n: Number, text: str, months: int) -> bool:
    after = text[n.end:n.end + 8].lower().lstrip(" -")
    return any(_same(n.value, v) and after.startswith(unit) for v, unit in _duration_values(months))


def check(spec: ProposalSpec, text: str | None) -> CheckResult:
    if not text or not text.strip():
        return CheckResult(False, ["empty"])
    lowered = text.lower()
    citations = [m.span() for m in _LAW.finditer(text)]
    numbers = [n for n in find_numbers(text) if not any(a <= n.start < b for a, b in citations)]
    reasons: list[str] = []
    spans: dict[str, tuple[int, int]] = {}

    if _SDG.search(text):
        reasons.append("mentions_sdg")

    # Duration first: it is the one fact identified by its unit ("12 months"),
    # so a target of 12 elsewhere cannot steal its label, nor it the target's.
    duration = next((n for n in numbers if _is_duration(n, text, spec.duration_months)), None)
    if duration is None:
        reasons.append("missing:duration")
    else:
        spans["duration"] = (duration.start, duration.end)

    required: dict[str, float] = {"target": spec.target, "amount": float(spec.amount)}
    if spec.beneficiaries is not None:
        required["beneficiaries"] = float(spec.beneficiaries)
    if spec.baseline is not None and not spec.zero_baseline:
        required["baseline"] = spec.baseline
    for name, value in required.items():
        claimed = set(spans.values())
        hit = next((n for n in numbers if _same(n.value, value) and (n.start, n.end) not in claimed), None)
        if hit is None:
            reasons.append(f"missing:{name}")
        else:
            spans[name] = (hit.start, hit.end)

    at = lowered.find(spec.district.lower())
    if at < 0:
        reasons.append("missing:district")
    else:
        spans["district"] = (at, at + len(spec.district))

    for activity in spec.activities:
        if not _activity_described(activity, lowered):
            reasons.append(f"missing_activity:{activity}")

    # Context counts must appear -- they are the distractors BERT has to learn
    # to ignore -- but they are never labels.
    for noun, n in spec.context:
        if not any(_same(x.value, n) for x in numbers):
            reasons.append(f"missing_context:{noun}")

    allowed = set(required.values()) | {float(spec.founded), float(spec.num_phases)}
    allowed |= {float(n) for _, n in spec.context}
    allowed |= {float(v) for v in SMALL_INTEGERS}
    allowed |= {v for v, _ in _duration_values(spec.duration_months)}
    allowed |= {n.value for n in find_numbers(spec.beneficiary_group)}
    if spec.budget_lines:
        allowed |= {float(amount) for _, amount in spec.budget_lines}
    if spec.baseline is not None and not spec.zero_baseline:
        allowed.add(abs(spec.target - spec.baseline))       # "an increase of 9 points"

    leaked = {name for name, value in spec.omitted.items()
              if not any(_same(value, a) for a in allowed) and any(_same(n.value, value) for n in numbers)}
    reasons.extend(f"leaked:{name}" for name in sorted(leaked))
    leaked_values = [spec.omitted[name] for name in leaked]
    for n in numbers:
        if any(_same(n.value, a) for a in allowed) or any(_same(n.value, v) for v in leaked_values):
            continue
        shown = int(n.value) if n.value == int(n.value) else n.value
        reason = f"invented:{shown}"
        if reason not in reasons:
            reasons.append(reason)

    return CheckResult(ok=not reasons, reasons=reasons, spans=spans if not reasons else {})
