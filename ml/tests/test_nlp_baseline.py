"""The rule-based reader BERT is compared against."""

from nlp.baseline import rule_read

TEXT = ("Asha Trust has served Gaya district, Bihar for years. Over 9 months we will run remedial "
        "classes and a daily midday meal for 3,200 students, raising attendance from 48% to 57%. "
        "We request Rs 18 lakh.")


def test_reads_sdgs_from_activity_keywords():
    assert rule_read(TEXT)["sdgs"] == {2, 4}


def test_reads_the_metric_from_its_wording():
    assert rule_read(TEXT)["metric"] == "attendance_rate"


def test_reads_fields_with_patterns():
    assert rule_read(TEXT)["fields"] == {"duration": 9, "beneficiaries": 3200, "baseline": 48,
                                         "target": 57, "amount": 1_800_000, "district": "Gaya"}


def test_a_single_percentage_is_read_as_the_target_not_the_baseline():
    fields = rule_read("We will raise attendance to 57% in Gaya over 9 months.")["fields"]
    assert fields.get("target") == 57 and "baseline" not in fields
