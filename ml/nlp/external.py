"""Evaluate the readers on text they did not train on.

    make eval-human     # the team's proposals in ml/datasets/human_test/proposals/<id>.txt
    make eval-unseen    # another LLM's rewrites of the test projects (make proposals-unseen)
    -> ml/results/nlp_external_metrics.json, one section per set

A hand-written proposal is scored on exactly the facts its fact sheet gave:
a fact the sheet withheld has no answer, so a reader that fills it in is
hallucinating. Rule breaks (an added number, a missing fact) are reported back
to the writer; the proposal is still scored, since readers must cope with them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from nlp.data import METRIC_LABELS, Example, build_examples
from textgen.checker import check
from textgen.generate import _goal, _in_words, _indian

HUMAN_DIR = Path("ml/datasets/human_test/proposals")
FACT_SHEETS = Path("ml/datasets/human_test/fact_sheets.md")
RESULTS = Path("ml/results/nlp_external_metrics.json")


def _stated(spec) -> set[str]:
    stated = {"target", "amount", "duration", "district"}
    if spec.beneficiaries is not None:
        stated.add("beneficiaries")
    if spec.baseline is not None and not spec.zero_baseline:
        stated.add("baseline")
    return stated


def human_examples(directory: Path, projects: pd.DataFrame, specs: dict) -> tuple[list[Example], dict]:
    """Examples from <project id>.txt files, and each writer's rule breaks."""
    labels = projects.set_index("project_id")
    examples, problems = [], {}
    for path in sorted(Path(directory).glob("*.txt")):
        if not path.stem.isdigit():
            problems[path.name] = ["file name is not a project id"]
            continue
        pid = int(path.stem)
        if pid not in specs:
            problems[pid] = ["unknown project id"]
            continue
        text = path.read_text().strip()
        result = check(specs[pid], text)
        if not result.ok:
            problems[pid] = result.reasons
        row = labels.loc[pid]
        examples.append(Example(
            project_id=pid, text=text, sdgs=list(row["sdgs"]),
            metric=METRIC_LABELS.index(row["metric_name"]),
            spans={field: (0, 0) for field in _stated(specs[pid])},   # which facts were stated; positions unused
            split=str(row["split"]), provider="human",
        ))
    return examples, problems


def write_fact_sheets(path: Path, specs: dict, project_ids: list[int]) -> None:
    """The sheets the team writes from, 10 per writer."""
    lines = [
        "# Fact sheets for the hand-written test set", "",
        "Each writer takes 10 sheets. Write the proposal the NGO would send a company's CSR team, "
        "in your own words, and save it as `proposals/<project id>.txt` (e.g. `proposals/1234.txt`). "
        "Then run `make eval-human` from the repo root.", "",
        "Rules, so the answers can be scored:", "",
        "1. Use every fact on the sheet, with the numbers **in digits** exactly as given "
        "(\"9 months\", not \"nine months\"; \"Rs 18 lakh\" or \"Rs 18,00,000\" are both fine).",
        "2. Mention each number under *Also mention*: these are counts of things, not of beneficiaries.",
        "3. Do not add other numbers - no other counts, percentages, amounts or years.",
        "4. Describe each activity in your own words; don't copy the activity names.",
        "5. Never state anything listed under *Do not state*.",
        "6. Don't mention the SDGs by name or number.",
        "7. Write naturally - any length from 100 to 300 words, any structure.", "",
    ]
    for n, pid in enumerate(project_ids):
        s = specs[pid]
        if n % 10 == 0:
            lines += [f"## Writer {'ABCD'[n // 10]}", ""]
        who = (f"{s.beneficiaries:,} {s.beneficiary_group}" if s.beneficiaries is not None
               else f"{s.beneficiary_group} (do not give a number)")
        lines += [f"### Project {pid}", "",
                  f"- **NGO:** {s.ngo_name}, founded {s.founded}",
                  f"- **Where:** {s.district} district, {s.state}",
                  f"- **Activities:** {'; '.join(s.activities)}",
                  f"- **Who benefits:** {who}",
                  f"- **Goal:** {_goal(s, s.metric_label)}",
                  f"- **Duration:** {s.duration_months} months",
                  f"- **Budget:** Rs {_indian(s.amount)} ({_in_words(s.amount)})"]
        if s.budget_lines:
            lines.append("- **Breakdown:** " + "; ".join(f"{i} Rs {_indian(a)}" for i, a in s.budget_lines))
        if s.context:
            lines.append("- **Also mention:** " + "; ".join(f"{n:,} {noun}" for noun, n in s.context))
        banned = (["the number of beneficiaries"] if s.beneficiaries is None else []) + \
                 ([f"the current {s.metric_label}"] if "baseline" in s.omitted else []) + \
                 (["a budget breakdown or line-item amounts"] if not s.budget_lines else [])
        if banned:
            lines.append("- **Do not state:** " + "; ".join(banned))
        lines.append("")
    Path(path).write_text("\n".join(lines))


def _summary(name: str, r: dict) -> str:
    f = r["fields"]
    return (f"{name:16} n={r['n']:<4} SDG micro-F1 {r['sdg']['micro_f1']:.3f}  metric acc {r['metric_accuracy']:.3f}  "
            f"fields acc {f['accuracy_on_stated']:.3f}  hallucination {f['hallucination_rate']:.3f}")


def main() -> None:
    from nlp.baseline import rule_read
    from nlp.evaluate import evaluate, reading_to_prediction
    from nlp.reader import ProposalReader
    from synth.build import load_world
    from textgen.generate import build_specs

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--human", action="store_true", help=f"score {HUMAN_DIR}/*.txt")
    group.add_argument("--jsonl", type=Path, help="score a generated proposals file")
    args = parser.parse_args()

    world = load_world(Path("ml/datasets"))
    problems = {}
    if args.human:
        specs = {s.project_id: s for s in build_specs(world.projects, world.ngos)}
        examples, problems = human_examples(HUMAN_DIR, world.projects, specs)
        name = "human_written"
    else:
        rows = [json.loads(line) for line in args.jsonl.read_text().splitlines() if line.strip()]
        examples, name = build_examples(rows, world.projects), args.jsonl.stem
    if not examples:
        raise SystemExit(f"nothing to score. Hand-written proposals go in {HUMAN_DIR}/<project id>.txt; "
                         f"the fact sheets are in {FACT_SHEETS}.")

    reader = ProposalReader.load(Path("ml/artifacts/bert"))
    projects = world.projects.set_index("project_id")
    results = {
        "bert": evaluate(lambda t: reading_to_prediction(reader.read(t)), examples, projects),
        "rule_baseline": evaluate(rule_read, examples, projects),
        "rule_breaks": {str(k): v for k, v in problems.items()},
    }
    report = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    report[name] = results
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, indent=2, default=str) + "\n")

    print(f"{name}: {len(examples)} proposals")
    for key in ("bert", "rule_baseline"):
        print(_summary(key, results[key]))
    for pid, reasons in problems.items():
        print(f"  rule breaks in {pid}: {', '.join(reasons)}")
    print(f"saved {RESULTS}")


if __name__ == "__main__":
    main()
