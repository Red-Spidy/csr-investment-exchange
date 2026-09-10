"""Claude-backed extraction of structured data from NGO proposals.

Design notes that matter:

* One call per proposal does field extraction AND SDG classification.
* The system prompt and few-shot examples are byte-identical on every call and
  carry cache breakpoints, so only the proposal text is billed at full rate.
  Check `usage.cache_read_input_tokens` -- a persistent zero means something is
  silently invalidating the prefix.
* Nothing here decides anything. It produces evidence; SQL decides.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import anthropic

from prompts import FEW_SHOT, PROMPT_VERSION, SYSTEM_PROMPT, USER_TEMPLATE
from schemas import Beneficiaries, Geography, ProposalExtraction, TargetMetric

MODEL = os.environ.get("EXTRACTION_MODEL", "claude-opus-5")
_LAKH, _CRORE = 100_000, 10_000_000


@dataclass
class ExtractionResult:
    extraction: ProposalExtraction
    model_version: str
    prompt_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    used_fallback: bool = False

    @property
    def cache_hit(self) -> bool:
        return self.cache_read_tokens > 0


def _cached(block: dict) -> dict:
    """Mark a content block as a cache breakpoint."""
    return {**block, "cache_control": {"type": "ephemeral"}}


def _build_messages(title: str, sector: str, proposal_text: str) -> list[dict]:
    messages: list[dict] = []
    for i, shot in enumerate(FEW_SHOT):
        block = {"type": "text", "text": shot["content"]}
        # Breakpoint on the final few-shot turn: everything above it is stable
        # across every proposal we will ever send.
        if i == len(FEW_SHOT) - 1:
            block = _cached(block)
        messages.append({"role": shot["role"], "content": [block]})

    messages.append({
        "role": "user",
        "content": USER_TEMPLATE.format(
            title=title, sector=sector, proposal_text=proposal_text
        ),
    })
    return messages


def extract_proposal(
    title: str,
    sector: str,
    proposal_text: str,
    client: anthropic.Anthropic | None = None,
    fallback_on_error: bool = True,
) -> ExtractionResult:
    """Extract one proposal. Falls back to rules if the API is unreachable."""
    client = client or anthropic.Anthropic()

    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=2000,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},  # extraction needs care, not depth
            system=[_cached({"type": "text", "text": SYSTEM_PROMPT})],
            messages=_build_messages(title, sector, proposal_text),
            output_format=ProposalExtraction,
        )
    except Exception:
        if not fallback_on_error:
            raise
        return ExtractionResult(
            extraction=rule_based_extract(proposal_text),
            model_version="rule-based-fallback",
            prompt_version=PROMPT_VERSION,
            used_fallback=True,
        )

    usage = response.usage
    return ExtractionResult(
        extraction=response.parsed_output,
        model_version=MODEL,
        prompt_version=PROMPT_VERSION,
        input_tokens=getattr(usage, "input_tokens", 0),
        output_tokens=getattr(usage, "output_tokens", 0),
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
    )


# --------------------------------------------------------------------------
# Batch path: the offline corpus run. Half price, and the right tool for
# scoring hundreds of proposals that nobody is waiting on.
# --------------------------------------------------------------------------

def submit_batch(proposals: list[dict], client: anthropic.Anthropic | None = None) -> str:
    """Submit proposals as one batch. `proposals` need id/title/sector/proposal_text."""
    client = client or anthropic.Anthropic()

    requests = [
        {
            "custom_id": f"proposal-{p['id']}",
            "params": {
                "model": MODEL,
                "max_tokens": 2000,
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": "low"},
                "system": [_cached({"type": "text", "text": SYSTEM_PROMPT})],
                "messages": _build_messages(
                    p["title"], p.get("sector", ""), p["proposal_text"]
                ),
            },
        }
        for p in proposals
    ]
    return client.messages.batches.create(requests=requests).id


def collect_batch(batch_id: str, client: anthropic.Anthropic | None = None) -> dict[int, ProposalExtraction]:
    """Read a finished batch. Results arrive in ANY order -- key by custom_id."""
    client = client or anthropic.Anthropic()
    out: dict[int, ProposalExtraction] = {}

    for entry in client.messages.batches.results(batch_id):
        if entry.result.type != "succeeded":
            continue
        project_id = int(entry.custom_id.rsplit("-", 1)[1])
        text = "".join(
            b.text for b in entry.result.message.content if getattr(b, "type", "") == "text"
        )
        try:
            out[project_id] = ProposalExtraction.model_validate_json(text)
        except Exception:
            continue  # caller reconciles against submitted ids
    return out


# --------------------------------------------------------------------------
# Offline fallback. Deliberately conservative: it is better for the pipeline to
# see nulls and route to manual review than to see a wrong number.
# --------------------------------------------------------------------------

_STATES = (
    "Rajasthan Bihar Maharashtra Karnataka Odisha Gujarat Kerala Punjab Assam "
    "Jharkhand Telangana Haryana"
).split()

_SDG_KEYWORDS: dict[int, tuple[str, ...]] = {
    1: ("poverty", "income support"),
    2: ("nutrition", "midday meal", "hunger", "malnutrition"),
    3: ("health", "disease", "antenatal", "maternal", "clinic", "anaemia"),
    4: ("school", "education", "attendance", "classroom", "literacy", "teacher"),
    5: ("women", "girl", "gender"),
    6: ("water", "sanitation", "toilet", "handpump", "hygiene"),
    7: ("solar", "energy", "electrification"),
    8: ("livelihood", "employment", "weaver", "artisan", "skill training"),
    13: ("climate", "carbon", "emission"),
    15: ("forest", "sapling", "biodiversity", "reforestation", "tree"),
}


def rule_based_extract(text: str) -> ProposalExtraction:
    """Regex fallback used when the API is unreachable (e.g. a demo with no wifi)."""
    lowered = text.lower()

    sdgs = [n for n, words in _SDG_KEYWORDS.items() if any(w in lowered for w in words)]

    duration = None
    if m := re.search(r"(\d+)\s*months?", lowered):
        duration = int(m.group(1))

    baseline = target = None
    pcts = [float(p) for p in re.findall(r"(\d+(?:\.\d+)?)\s*%", text)]
    if len(pcts) >= 2:
        baseline, target = pcts[0], pcts[1]
    elif len(pcts) == 1:
        baseline = pcts[0]

    count = None
    if m := re.search(r"([\d,]{3,})\s+(?:students|residents|children|women|people|beneficiaries)", lowered):
        count = int(m.group(1).replace(",", ""))

    state = next((s for s in _STATES if s.lower() in lowered), None)
    district = None
    if m := re.search(r"in ([A-Z][a-z]+) district", text):
        district = m.group(1)

    return ProposalExtraction(
        goals=[],  # never guessed: goals are exactly what rules cannot recover
        target_metric=TargetMetric(baseline=baseline, target=target) if baseline else None,
        beneficiaries=Beneficiaries(count=count, group=None) if count else None,
        geography=Geography(state=state, district=district) if state or district else None,
        duration_months=duration,
        sdgs=sdgs,
        sdg_confidence={str(n): 0.35 for n in sdgs},  # low: rules are not calibrated
        red_flags=["extracted by rule-based fallback; requires manual review"],
    )


def parse_inr(phrase: str) -> float | None:
    """'50 lakh' -> 5000000.0, '2 crore' -> 20000000.0. None if unparseable."""
    if m := re.search(r"(\d+(?:\.\d+)?)\s*lakh", phrase, re.I):
        return float(m.group(1)) * _LAKH
    if m := re.search(r"(\d+(?:\.\d+)?)\s*crore", phrase, re.I):
        return float(m.group(1)) * _CRORE
    if m := re.search(r"(\d[\d,]*)", phrase):
        return float(m.group(1).replace(",", ""))
    return None
