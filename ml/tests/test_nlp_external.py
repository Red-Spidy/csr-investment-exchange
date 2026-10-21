"""Evaluating readers on text they never trained on: the team's hand-written
proposals, and another LLM's rewrites of the test projects."""

import pytest

from nlp.external import human_examples
from synth.world import generate_world
from textgen.generate import build_specs


@pytest.fixture(scope="module")
def small():
    w = generate_world(seed=3, n_ngos=40, n_projects=60)
    return w, {s.project_id: s for s in build_specs(w.projects, w.ngos)}


def test_a_hand_written_proposal_is_scored_on_exactly_the_facts_its_sheet_gave(small, tmp_path):
    w, specs = small
    vague = next(s for s in specs.values() if s.beneficiaries is None and "baseline" in s.omitted)
    full = next(s for s in specs.values() if s.beneficiaries is not None and s.baseline is not None
                and not s.zero_baseline)
    for s in (vague, full):
        (tmp_path / f"{s.project_id}.txt").write_text(f"Proposal for project {s.project_id}.")
    (tmp_path / "notes.md").write_text("not a proposal")
    examples, problems = human_examples(tmp_path, w.projects, specs)
    by_id = {e.project_id: e for e in examples}
    assert set(by_id) == {vague.project_id, full.project_id}
    # Facts the sheet withheld must be absent, so filling them in counts as invented.
    assert set(by_id[vague.project_id].spans) == {"target", "amount", "duration", "district"}
    assert set(by_id[full.project_id].spans) == {"beneficiaries", "baseline", "target", "amount",
                                                  "duration", "district"}
    assert by_id[full.project_id].provider == "human"


def test_rule_breaks_are_reported_back_to_the_writer(small, tmp_path):
    w, specs = small
    s = next(iter(specs.values()))
    (tmp_path / f"{s.project_id}.txt").write_text("We will help many people. This supports SDG 4.")
    _, problems = human_examples(tmp_path, w.projects, specs)
    assert any("mentions_sdg" in r for r in problems[s.project_id])
    assert any(r.startswith("missing:") for r in problems[s.project_id])


def test_a_file_for_an_unknown_project_is_skipped_and_reported(small, tmp_path):
    w, specs = small
    (tmp_path / "999999.txt").write_text("text")
    examples, problems = human_examples(tmp_path, w.projects, specs)
    assert examples == [] and problems[999999] == ["unknown project id"]
