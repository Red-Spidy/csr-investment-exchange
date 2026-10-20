"""Generate BERT's training proposals: facts from the synthetic world, prose from
an LLM, every proposal checked before it is kept.

    make proposals LIMIT=300    # pilot: look at quality before the full run
    make proposals              # everything still missing

Accepted proposals are appended to ml/datasets/proposals.jsonl one at a time,
so a run stopped by a daily quota resumes where it left off. Labels are not
stored here: SDGs and facts come from projects.csv, joined on project_id.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter, deque
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from synth.build import load_world
from synth.catalog import SECTOR_PROFILE
from textgen.checker import check
from textgen.router import (REQUEST_TIMEOUT, AllProvidersUnavailable, Router, parse_batch,
                            providers_from_env)
from textgen.spec import ProposalSpec

PROMPT_VERSION = "p1"
DATASETS = Path("ml/datasets")
OUT = DATASETS / "proposals.jsonl"
BATCH_SIZE = 10
MAX_ATTEMPTS = 3
STYLE_SEED = 1021

# Varied voices so BERT learns content, not one register.
STYLES = (
    "a formal grant proposal with short headed sections",
    "a plain-language note from a small rural NGO",
    "a narrative that opens with one beneficiary's situation",
    "a bullet-point summary by a programme manager",
    "a technical proposal that explains how progress will be monitored",
    "a persuasive appeal from the NGO's founder",
    "a concise email to a company's CSR team",
    "a proposal written in slightly non-native, Indian-English phrasing",
)
LENGTHS = (120, 180, 250, 320)

SYSTEM_PROMPT = """You write realistic project proposals from Indian NGOs applying \
for CSR funding under Section 135 of the Companies Act.

For each set of facts you are given, write the proposal that NGO would submit.

Rules:
1. Use every fact given, with exactly the numbers given. Write every number in digits.
2. Do not add any other number: no other counts, percentages, amounts, dates or years.
3. Describe every listed activity, in your own words.
4. Never mention anything listed under "Do not state".
5. Do not mention the Sustainable Development Goals or SDG numbers.
6. Follow the requested style and length. Vary vocabulary and structure between
   proposals; do not reuse phrasing.

Return only a JSON array with one object per proposal:
[{"id": <id>, "proposal": "<text>"}]"""


# --------------------------------------------------------------------- specs

def _metric(name: str):
    return next(m for p in SECTOR_PROFILE.values() for m in p.metrics if m.name == name)


def build_specs(projects: pd.DataFrame, ngos: pd.DataFrame) -> list[ProposalSpec]:
    """One spec per project. What a project does not state is withheld from
    the spec entirely and recorded under `omitted` for the checker."""
    ngo = ngos.set_index("ngo_id")
    specs = []
    for p in projects.itertuples(index=False):
        metric = _metric(p.metric_name)
        zero = metric.baseline_range == (0, 0)
        omitted: dict[str, float] = {}

        beneficiaries = int(p.beneficiaries) if p.states_beneficiaries else None
        if beneficiaries is None:
            omitted["beneficiaries"] = float(p.beneficiaries)
        if zero:
            baseline = 0.0
        elif p.states_baseline:
            baseline = float(p.baseline)
        else:
            baseline = None
            omitted["baseline"] = float(p.baseline)

        rng = np.random.default_rng([STYLE_SEED, int(p.project_id)])
        specs.append(ProposalSpec(
            project_id=int(p.project_id),
            ngo_name=str(ngo.loc[p.ngo_id, "name"]),
            founded=int(ngo.loc[p.ngo_id, "established_year"]),
            sector=p.sector, title=p.title, state=p.state, district=p.district,
            activities=tuple(p.activities),
            beneficiary_group=p.beneficiary_group,
            beneficiaries=beneficiaries,
            metric_label=p.metric_name.replace("_", " "),
            metric_unit=p.metric_unit,
            baseline=baseline,
            target=float(p.target),
            zero_baseline=zero,
            amount=int(p.requested_amount),
            duration_months=int(p.duration_months),
            num_phases=int(p.num_phases),
            budget_lines=(tuple((line["item"], int(line["amount"])) for line in p.budget_lines)
                          if p.states_budget_breakdown else None),
            omitted=omitted,
            style=STYLES[rng.integers(len(STYLES))],
            length_words=int(LENGTHS[rng.integers(len(LENGTHS))]),
            metric_direction=metric.direction,
        ))
    return specs


# --------------------------------------------------------------------- prompt

def _indian(n: int) -> str:
    """18,00,000 -- the grouping Indian proposals use."""
    s = str(n)
    if len(s) <= 3:
        return s
    head, groups = s[:-3], [s[-3:]]
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head, *groups] if head else groups)


def _in_words(n: int) -> str:
    return f"{n / 10_000_000:g} crore" if n >= 10_000_000 else f"{n / 100_000:g} lakh"


def _goal(spec: ProposalSpec) -> str:
    label, t, b = spec.metric_label, spec.target, spec.baseline
    if spec.metric_unit == "hectares":
        return f"add {t:g} hectares of {label}"
    if spec.metric_unit == "tonnes_per_month":
        return f"divert {t:g} tonnes of waste per month from landfill"
    if spec.metric_unit == "percent_increase":
        return f"raise {label} by {t:g}%"
    verb = "reduce" if spec.metric_direction == "decrease" else "raise"
    return f"{verb} {label} from {b:g}% to {t:g}%" if b is not None else f"{verb} {label} to {t:g}%"


def _facts(spec: ProposalSpec) -> str:
    who = (f"{spec.beneficiaries:,} {spec.beneficiary_group}" if spec.beneficiaries is not None
           else f"{spec.beneficiary_group} (do not give a number)")
    lines = [
        f"Proposal id: {spec.project_id}",
        f"NGO: {spec.ngo_name}, founded {spec.founded}",
        f"Location: {spec.district} district, {spec.state}",
        f"Activities: {'; '.join(spec.activities)}",
        f"Who benefits: {who}",
        f"Goal: {_goal(spec)}",
        f"Duration: {spec.duration_months} months",
        f"Total budget: Rs {_indian(spec.amount)} ({_in_words(spec.amount)})",
    ]
    if spec.budget_lines:
        lines.append("Budget breakdown: " + "; ".join(f"{item} Rs {_indian(a)}" for item, a in spec.budget_lines))
    banned = []
    if spec.beneficiaries is None:
        banned.append("the number of beneficiaries")
    if "baseline" in spec.omitted:
        banned.append(f"the current {spec.metric_label}")
    if not spec.budget_lines:
        banned.append("a budget breakdown or any line-item amount")
    banned.append("any number not listed above")
    lines.append("Do not state: " + "; ".join(banned))
    lines.append(f"Style: {spec.style}, about {spec.length_words} words")
    return "\n".join(lines)


def batch_prompt(specs: list[ProposalSpec]) -> str:
    return ("Write one proposal for each set of facts below.\n\n"
            + "\n\n".join(_facts(s) for s in specs)
            + '\n\nReturn only the JSON array: [{"id": <id>, "proposal": "<text>"}]')


# --------------------------------------------------------------------- loop

def _saved_ids(path: Path) -> set[int]:
    if not path.exists():
        return set()
    return {json.loads(line)["project_id"] for line in path.read_text().splitlines() if line.strip()}


def generate(specs: list[ProposalSpec], router, out_path: Path, batch_size: int = BATCH_SIZE,
             max_attempts: int = MAX_ATTEMPTS, limit: int | None = None, log=lambda msg: None) -> dict:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = _saved_ids(out_path)
    todo = [s for s in specs if s.project_id not in done]
    queue = deque(todo if limit is None else todo[:limit])

    attempts: Counter = Counter()
    reasons: Counter = Counter()
    by_provider: Counter = Counter()
    stats = {"accepted": 0, "gave_up": 0, "stopped": None}

    with out_path.open("a") as fh:
        while queue:
            batch = [queue.popleft() for _ in range(min(batch_size, len(queue)))]
            try:
                completion = router.complete(SYSTEM_PROMPT, batch_prompt(batch))
            except AllProvidersUnavailable as err:
                queue.extendleft(reversed(batch))
                stats["stopped"] = str(err)
                break
            texts = parse_batch(completion.text)
            for spec in batch:
                result = check(spec, texts.get(spec.project_id))
                if result.ok:
                    fh.write(json.dumps({
                        "project_id": spec.project_id,
                        "text": texts[spec.project_id],
                        "spans": {k: list(v) for k, v in result.spans.items()},
                        "provider": completion.provider,
                        "model": completion.model,
                        "style": spec.style,
                        "length_words": spec.length_words,
                        "prompt_version": PROMPT_VERSION,
                    }) + "\n")
                    fh.flush()
                    stats["accepted"] += 1
                    by_provider[completion.provider] += 1
                    continue
                attempts[spec.project_id] += 1
                reasons.update(r.split(":")[0] for r in result.reasons)
                if attempts[spec.project_id] < max_attempts:
                    queue.append(spec)
                else:
                    stats["gave_up"] += 1
            log(f"{completion.provider}: accepted {stats['accepted']}, queued {len(queue)}, "
                f"gave up {stats['gave_up']}")

    stats.update(remaining=len(queue), by_provider=dict(by_provider), rejection_reasons=dict(reasons))
    return stats


# --------------------------------------------------------------------- CLI

_ENV_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; comments, blanks and malformed lines are skipped."""
    env = {}
    for line in Path(path).read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = _ENV_LINE.match(line)
        if m:
            env[m.group(1)] = m.group(2).strip("'\"")
    return env


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None, help="generate at most this many new proposals")
    parser.add_argument("--batch", type=int, default=BATCH_SIZE)
    args = parser.parse_args()

    env = {**(read_env_file(Path(".env")) if Path(".env").exists() else {}), **os.environ}
    client = httpx.Client(timeout=REQUEST_TIMEOUT)
    providers = providers_from_env(env, client)
    if not providers:
        raise SystemExit("No usable API keys. Add GEMINI_API_KEY and/or GROQ_API_KEY to .env "
                         "(see .env.example), then run `make proposals` again.")
    router = Router(providers, client=client)
    print("providers: " + ", ".join(f"{p.name} ({p.model})" for p in providers))

    world = load_world(DATASETS)
    specs = build_specs(world.projects, world.ngos)
    started = time.monotonic()
    stats = generate(specs, router, OUT, batch_size=args.batch, limit=args.limit, log=print)
    total = len(_saved_ids(OUT))

    print(f"\naccepted {stats['accepted']}, gave up {stats['gave_up']}, still queued {stats['remaining']} "
          f"in {(time.monotonic() - started) / 60:.1f} min | {OUT}: {total} of {len(specs)} proposals")
    print(f"by provider: {stats['by_provider']} | rejection reasons: {stats['rejection_reasons']}")
    if stats["stopped"]:
        print(f"stopped early: {stats['stopped']}. Run `make proposals` again later to resume.")


if __name__ == "__main__":
    main()
