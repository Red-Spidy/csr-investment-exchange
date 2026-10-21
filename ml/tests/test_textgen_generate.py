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
    parts.extend(f"The work covers {n:,} {noun}." for noun, n in spec.context)
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
    # Full reasons, not just categories, so a pilot shows WHICH fact failed.
    assert any(reason.startswith("missing:") for reason in stats["top_rejections"])


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
    assert re.search(r": raise [a-z' -]+ to \d", batch_prompt([no_base]))
    falling = replace(rising, metric_label="waterborne disease incidence", metric_unit="percent",
                      metric_direction="decrease", baseline=None, target=12.0, omitted={"baseline": 18.0})
    assert re.search(r": reduce [a-z' -]+ to 12%", batch_prompt([falling]))


def test_every_activity_description_passes_the_checkers_keyword_rule():
    # If the LLM copies a description, the checker must still accept it.
    from synth.catalog import ACTIVITY_DESCRIPTIONS, SECTOR_PROFILE
    from textgen.checker import _activity_described
    activities = {a for p in SECTOR_PROFILE.values() for a in p.activities}
    assert set(ACTIVITY_DESCRIPTIONS) == activities
    for activity, descriptions in ACTIVITY_DESCRIPTIONS.items():
        assert len(descriptions) >= 2, activity
        for d in descriptions:
            assert _activity_described(activity, d.lower()), (activity, d)


def test_fact_sheets_vary_in_order_and_wording_but_are_stable_per_project(specs):
    def middle(spec):
        lines = batch_prompt([spec]).split("\n\n")[1].splitlines()
        assert lines[0].startswith("Proposal id:")
        assert lines[-2].startswith("Do not state:") and lines[-1].startswith("Style:")
        return tuple(line.split(":")[0] for line in lines[1:-2])
    orders = {middle(s) for s in specs[:30]}
    assert len(orders) >= 10
    assert batch_prompt([specs[0]]) == batch_prompt([specs[0]])


def test_fact_sheet_does_not_hand_over_catalogue_activity_names(specs):
    copied = sum(a in batch_prompt([s]) for s in specs for a in s.activities)
    total = sum(len(s.activities) for s in specs)
    assert copied / total < 0.3


def test_every_metric_and_budget_item_has_alternative_phrasings():
    # A missing entry would crash the run partway through 2,000 proposals.
    from synth.catalog import ADMIN_BUDGET_ITEM, BUDGET_ITEM_PHRASES, METRIC_PHRASES, SECTOR_PROFILE
    labels = {m.name.replace("_", " ") for p in SECTOR_PROFILE.values() for m in p.metrics}
    items = {i for p in SECTOR_PROFILE.values() for i in p.budget_items} | {ADMIN_BUDGET_ITEM}
    assert labels <= set(METRIC_PHRASES) and items <= set(BUDGET_ITEM_PHRASES)
    assert all(len(v) >= 2 for v in [*METRIC_PHRASES.values(), *BUDGET_ITEM_PHRASES.values()])


def test_catalogue_budget_and_metric_names_are_not_handed_over_every_time(specs):
    from synth.catalog import ADMIN_BUDGET_ITEM
    with_breakdown = [s for s in specs if s.budget_lines]
    admin = sum(ADMIN_BUDGET_ITEM in batch_prompt([s]) for s in with_breakdown) / len(with_breakdown)
    metric = sum(s.metric_label in batch_prompt([s]) for s in specs) / len(specs)
    assert admin < 0.5 and metric < 0.6


def test_most_specs_carry_unlabelled_context_numbers_that_never_equal_a_fact(specs):
    with_context = [s for s in specs if s.context]
    assert 0.5 <= len(with_context) / len(specs) <= 0.9
    for s in with_context:
        facts = {s.beneficiaries, s.baseline, s.target, s.amount, s.duration_months, s.founded, s.num_phases,
                 *s.omitted.values()}
        assert all(n not in facts for _, n in s.context), s.project_id
    assert [s.context for s in specs] == [s.context for s in build_specs(
        generate_world(seed=3, n_ngos=40, n_projects=60).projects,
        generate_world(seed=3, n_ngos=40, n_projects=60).ngos)]


def test_prompt_lists_context_numbers_as_not_the_beneficiary_count(specs):
    spec = next(s for s in specs if s.context)
    prompt = batch_prompt([spec])
    noun, n = spec.context[0]
    assert f"{n:,} {noun}" in prompt and "not the number of beneficiaries" in prompt


def test_an_unseen_writer_set_covers_only_the_requested_split(specs):
    from textgen.generate import specs_for_split
    w = generate_world(seed=3, n_ngos=40, n_projects=60)
    test_ids = set(w.projects.loc[w.projects["split"] == "test", "project_id"])
    chosen = specs_for_split(specs, w.projects, "test")
    assert chosen and {s.project_id for s in chosen} == test_ids & {s.project_id for s in specs}


def test_provider_choice_keeps_only_those_keys():
    from textgen.generate import env_for_providers
    env = {"GEMINI_API_KEY": "g", "GROQ_API_KEY": "q", "GROQ_MODEL": "m", "DATABASE_URL": "x"}
    assert env_for_providers(env, ["groq"]) == {"GROQ_API_KEY": "q", "GROQ_MODEL": "m", "DATABASE_URL": "x"}
    assert env_for_providers(env, None) == env
