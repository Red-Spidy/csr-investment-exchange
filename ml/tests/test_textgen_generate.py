"""Proposal generation: specs from the world, prompts, and the resumable loop.
The router is replaced by a scripted stand-in; the real one has its own tests."""

import json
import re

import pytest

from synth.world import generate_world
from textgen.generate import batch_prompt, build_specs, generate, read_env_file
from textgen.router import AllProvidersUnavailable, Completion


@pytest.fixture(scope="module")
def specs():
    w = generate_world(seed=3, n_ngos=40, n_projects=60)
    return build_specs(w.projects, w.ngos)


def _faithful(spec) -> str:
    """What a well-behaved LLM would write: every fact, nothing else."""
    parts = [f"{spec.ngo_name}, founded in {spec.founded}, works in {spec.district} district, {spec.state}."]
    parts.append("We will run " + " and ".join(spec.activities) + f" over {spec.duration_months} months.")
    if spec.beneficiaries is not None:
        parts.append(f"The project reaches {spec.beneficiaries:,} {spec.beneficiary_group}.")
    if spec.baseline is not None and not spec.zero_baseline:
        parts.append(f"Our {spec.metric_label} stands at {spec.baseline:g} and we aim for {spec.target:g}.")
    else:
        parts.append(f"We aim for {spec.target:g} on {spec.metric_label}.")
    parts.append(f"We request Rs {spec.amount:,}.")
    if spec.budget_lines:
        parts.append("Breakdown: " + "; ".join(f"{item} Rs {amount:,}" for item, amount in spec.budget_lines) + ".")
    return " ".join(parts)


class ScriptedRouter:
    """Answers each batch prompt by writing the proposals the script says to."""

    def __init__(self, by_id, writer=_faithful, fail_with=None):
        self.by_id, self.writer, self.fail_with = by_id, writer, fail_with
        self.prompted_ids = []

    def complete(self, system, user):
        if self.fail_with:
            raise self.fail_with
        ids = [int(x) for x in re.findall(r"Proposal id: (\d+)", user)]
        self.prompted_ids.extend(ids)
        items = [{"id": i, "proposal": self.writer(self.by_id[i])} for i in ids]
        return Completion("```json\n" + json.dumps(items) + "\n```", "fake", "fake-model")


def _saved(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_specs_state_only_what_each_project_states(specs):
    w = generate_world(seed=3, n_ngos=40, n_projects=60)
    projects = w.projects.set_index("project_id")
    for spec in specs:
        p = projects.loc[spec.project_id]
        if p["states_beneficiaries"]:
            assert spec.beneficiaries == p["beneficiaries"]
        else:
            assert spec.beneficiaries is None and spec.omitted["beneficiaries"] == p["beneficiaries"]
        assert (spec.budget_lines is None) == (not p["states_budget_breakdown"])
    assert any(s.zero_baseline for s in specs) and any(not s.zero_baseline for s in specs)


def test_prompt_carries_the_facts_but_never_an_omitted_value(specs):
    vague = next(s for s in specs if s.beneficiaries is None)
    prompt = batch_prompt([vague])
    assert f"Proposal id: {vague.project_id}" in prompt
    assert vague.district in prompt and f"{vague.duration_months} months" in prompt
    assert "number of beneficiaries" in prompt
    # If the prompt carried the true count, the LLM would likely write it.
    assert f"{vague.omitted['beneficiaries']:,}" not in prompt
    assert str(vague.omitted["beneficiaries"]) not in prompt


def test_writing_styles_vary_and_are_stable_per_project(specs):
    assert len({s.style for s in specs}) >= 4
    again = build_specs(generate_world(seed=3, n_ngos=40, n_projects=60).projects,
                        generate_world(seed=3, n_ngos=40, n_projects=60).ngos)
    assert [s.style for s in again] == [s.style for s in specs]


def test_faithful_proposals_are_saved_with_provenance_and_spans(specs, tmp_path):
    out = tmp_path / "proposals.jsonl"
    router = ScriptedRouter({s.project_id: s for s in specs})
    stats = generate(specs[:12], router, out, batch_size=5)
    saved = _saved(out)
    assert stats["accepted"] == 12 and len(saved) == 12
    first = saved[0]
    assert (first["provider"], first["model"]) == ("fake", "fake-model")
    start, end = first["spans"]["district"]
    spec = next(s for s in specs if s.project_id == first["project_id"])
    assert first["text"][start:end].lower() == spec.district.lower()


def test_rejected_proposals_are_retried_then_given_up(specs, tmp_path):
    out = tmp_path / "proposals.jsonl"
    bad_id = specs[0].project_id
    writer = lambda s: "We will do good work." if s.project_id == bad_id else _faithful(s)
    router = ScriptedRouter({s.project_id: s for s in specs}, writer=writer)
    stats = generate(specs[:4], router, out, batch_size=4, max_attempts=3)
    assert router.prompted_ids.count(bad_id) == 3
    assert stats["accepted"] == 3 and stats["gave_up"] == 1
    assert bad_id not in {r["project_id"] for r in _saved(out)}


def test_resumes_without_redoing_saved_proposals(specs, tmp_path):
    out = tmp_path / "proposals.jsonl"
    by_id = {s.project_id: s for s in specs}
    generate(specs[:3], ScriptedRouter(by_id), out, batch_size=3)
    router = ScriptedRouter(by_id)
    generate(specs[:6], router, out, batch_size=3)
    assert set(router.prompted_ids) == {s.project_id for s in specs[3:6]}
    assert len(_saved(out)) == 6


def test_stops_cleanly_and_keeps_progress_when_quota_runs_out(specs, tmp_path):
    out = tmp_path / "proposals.jsonl"
    generate(specs[:2], ScriptedRouter({s.project_id: s for s in specs}), out, batch_size=2)
    router = ScriptedRouter({}, fail_with=AllProvidersUnavailable(9999.0, "quota gone"))
    stats = generate(specs[:6], router, out, batch_size=2)
    assert stats["stopped"] == "quota gone"
    assert len(_saved(out)) == 2


def test_reads_keys_from_an_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\nGEMINI_API_KEY="abc"\n\nGROQ_API_KEY=xyz\nBROKEN LINE\n')
    assert read_env_file(env) == {"GEMINI_API_KEY": "abc", "GROQ_API_KEY": "xyz"}


def test_goal_says_raise_or_reduce_by_metric_direction_even_without_a_baseline(specs):
    from dataclasses import replace
    rising = next(s for s in specs if s.metric_unit == "percentage_points")
    no_base = replace(rising, baseline=None, omitted={"baseline": rising.baseline or 50.0})
    assert f"Goal: raise {rising.metric_label} to" in batch_prompt([no_base])
    falling = replace(rising, metric_label="waterborne disease incidence", metric_unit="percent",
                      metric_direction="decrease", baseline=None, target=12.0, omitted={"baseline": 18.0})
    assert "Goal: reduce waterborne disease incidence to 12%" in batch_prompt([falling])
