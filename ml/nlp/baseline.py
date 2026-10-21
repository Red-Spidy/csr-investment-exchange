"""A rule-based proposal reader: the bar the BERT readers have to clear.

Keywords for SDGs and the metric, number patterns for the fields. On our
generated corpus this baseline is flattered: the checker only accepts a
proposal when each activity's keywords appear, so keyword SDG matching is
nearly guaranteed to work there. The fair comparison is on text the checker
never shaped -- the team-written proposals.
"""

from __future__ import annotations

import re

from synth.anchors import STATE_DISTRICTS
from synth.catalog import SECTOR_PROFILE
from textgen.checker import _activity_described, find_numbers

_ACTIVITY_SDGS = {a: sdgs for p in SECTOR_PROFILE.values() for a, sdgs in p.activities.items()}
_DISTRICTS = [d for districts in STATE_DISTRICTS.values() for d in districts]
_METRIC_WORDS = {
    "attendance_rate": ("attendance",),
    "learning_outcome_score": ("learning outcome", "learning level", "assessment score", "test score"),
    "antenatal_coverage": ("antenatal",),
    "child_immunisation_rate": ("immunis", "immuniz", "vaccinat"),
    "waterborne_disease_incidence": ("waterborne", "diarrh"),
    "households_with_safe_water": ("safe water", "safe drinking water", "drinking water"),
    "tree_cover": ("hectare", "tree cover", "green cover", "forest cover"),
    "waste_diverted": ("tonne", "landfill"),
    "household_monthly_income": ("income", "earning"),
    "women_in_paid_work": ("paid work", "women earning", "women's participation"),
}
_BENEFICIARY = re.compile(
    r"^\W{0,3}(?:\w+\s){0,3}?(students|children|girls|boys|women|mothers|residents|households|farmers|"
    r"weavers|artisans|people|members|beneficiaries|villagers|families|participants|youth)", re.IGNORECASE)


def _int(value: float):
    return int(value) if value == int(value) else value


def rule_read(text: str) -> dict:
    lowered = text.lower()
    sdgs = {g for activity, goals in _ACTIVITY_SDGS.items() if _activity_described(activity, lowered)
            for g in goals}
    hits = {m: sum(lowered.count(w) for w in words) for m, words in _METRIC_WORDS.items()}
    metric = max(hits, key=hits.get)

    numbers = find_numbers(text)
    used, fields = set(), {}

    def after(n, length=12):
        return text[n.end:n.end + length].lower().lstrip(" -")

    duration = next((n for n in numbers if after(n).startswith(("month", "year"))), None)
    if duration:
        fields["duration"] = _int(duration.value * (12 if after(duration).startswith("year") else 1))
        used.add(duration)

    amount = next((n for n in numbers if n not in used and (
        re.search(r"(rs\.?|₹|inr)\s*$", text[max(0, n.start - 6):n.start].lower())
        or re.search(r"lakh|crore|million", text[n.start:n.end].lower()))), None)
    if amount:
        fields["amount"] = _int(amount.value)
        used.add(amount)

    percents = [n for n in numbers if n not in used and after(n, 9).startswith(("%", "per cent", "percent"))]
    if len(percents) >= 2:
        fields["baseline"], fields["target"] = _int(percents[0].value), _int(percents[1].value)
    elif len(percents) == 1:
        fields["target"] = _int(percents[0].value)
    else:
        quantity = next((n for n in numbers if n not in used and after(n).startswith(("hectare", "tonne"))), None)
        if quantity:
            fields["target"] = _int(quantity.value)
    used.update(percents)

    beneficiaries = next((n for n in numbers if n not in used and _BENEFICIARY.match(text[n.end:n.end + 40])), None)
    if beneficiaries:
        fields["beneficiaries"] = _int(beneficiaries.value)

    district = next((d for d in _DISTRICTS if d.lower() in lowered), None)
    if district:
        fields["district"] = district
    return {"sdgs": sdgs, "metric": metric, "fields": fields}
