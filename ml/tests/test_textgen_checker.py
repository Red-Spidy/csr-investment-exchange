"""The checker decides which LLM-written proposals become BERT training data.
A proposal that slips through with a wrong number becomes a wrong label."""

import pytest

from textgen.checker import check, find_numbers
from textgen.spec import ProposalSpec

GOOD = (
    "Jyoti Trust has worked in Gaya's rural blocks since 2014. Students in grades 6-8 "
    "here fall behind because their schools have no digital material. Over 9 months we "
    "will set up digital classrooms and run teacher training, reaching about 3,200 "
    "students. Average learning scores are 48% today; we aim for 57%. We request "
    "Rs 18 lakh for the work in Gaya district, Bihar."
)


def _spec(**overrides) -> ProposalSpec:
    fields = dict(
        project_id=17, ngo_name="Jyoti Trust", founded=2014, sector="education",
        title="Digital classrooms and teacher training, Gaya", state="Bihar", district="Gaya",
        activities=("digital classrooms", "teacher training"),
        beneficiary_group="students in grades 6-8", beneficiaries=3200,
        metric_label="learning outcome score", metric_unit="percentage_points",
        baseline=48.0, target=57.0, zero_baseline=False, amount=1_800_000, duration_months=9,
        num_phases=2, budget_lines=None, omitted={}, style="plain", length_words=150,
    )
    fields.update(overrides)
    return ProposalSpec(**fields)


@pytest.mark.parametrize("text, value", [
    ("Rs 18 lakh", 1_800_000),
    ("₹18,00,000", 1_800_000),
    ("INR 1,800,000", 1_800_000),
    ("1.8 million rupees", 1_800_000),
    ("Rs. 1.2 crore", 12_000_000),
    ("9.2 lakhs", 920_000),
    ("48%", 48),
    ("grades 6-8", 6),
])
def test_reads_numbers_in_indian_and_western_formats(text, value):
    assert value in [n.value for n in find_numbers(text)]


def test_accepts_a_faithful_proposal_and_records_where_each_fact_is():
    result = check(_spec(), GOOD)
    assert result.ok, result.reasons
    for field, needle in [("beneficiaries", "3,200"), ("baseline", "48"), ("target", "57"),
                          ("amount", "18 lakh"), ("duration", "9"), ("district", "Gaya")]:
        start, end = result.spans[field]
        assert GOOD[start:end] == needle, field


def test_rejects_a_missing_fact():
    result = check(_spec(), GOOD.replace("about 3,200 students", "many students"))
    assert not result.ok
    assert "missing:beneficiaries" in result.reasons


def test_rejects_a_fact_it_was_told_to_leave_out():
    spec = _spec(baseline=None, omitted={"baseline": 48.0})
    result = check(spec, GOOD)
    assert not result.ok
    assert "leaked:baseline" in result.reasons


def test_rejects_an_invented_number():
    result = check(_spec(), GOOD.replace("reaching about", "across 40 schools, reaching about"))
    assert not result.ok
    assert "invented:40" in result.reasons


def test_rejects_an_activity_the_text_never_describes():
    # SDG labels come from the activities; an undescribed one is a wrong label.
    result = check(_spec(), GOOD.replace(" and run teacher training", ""))
    assert not result.ok
    assert "missing_activity:teacher training" in result.reasons


def test_rejects_naming_sdgs_outright():
    # BERT must learn SDGs from what the project does, not read "SDG 4".
    result = check(_spec(), GOOD + " This supports SDG 4 on quality education.")
    assert not result.ok
    assert "mentions_sdg" in result.reasons


def test_duration_may_be_stated_in_years():
    spec = _spec(duration_months=24)
    text = GOOD.replace("Over 9 months", "Over 2 years")
    assert check(spec, text).ok


def test_zero_baseline_metrics_need_only_the_target():
    spec = _spec(sector="environment", activities=("native sapling plantation", "check dam construction"),
                 metric_label="tree cover", metric_unit="hectares", baseline=0.0, target=250.0,
                 zero_baseline=True, beneficiary_group="community members", beneficiaries=4000,
                 amount=2_400_000)
    text = ("Jyoti Trust, founded in 2014, will plant native saplings and build check dams in "
            "Gaya district, Bihar over 9 months, adding 250 hectares of tree cover for 4,000 "
            "community members. The budget is Rs 24 lakh.")
    assert check(spec, text).ok, check(spec, text).reasons


def test_a_number_shared_by_two_facts_is_labelled_at_the_right_place():
    # Duration 12 months and a target of 12%: each label must point at its own "12".
    spec = _spec(duration_months=12, baseline=18.0, target=12.0)
    text = ("Jyoti Trust, founded in 2014, will run digital classrooms and teacher training "
            "in Gaya district, Bihar for 12 months, reaching 3,200 students. We will cut the "
            "learning outcome score gap from 18% to 12%. We request Rs 18 lakh.")
    result = check(spec, text)
    assert result.ok, result.reasons
    duration, target = result.spans["duration"], result.spans["target"]
    assert text[duration[1]:duration[1] + 7] == " months"
    assert text[target[1]] == "%"
