"""From per-token tag scores back to field values in the proposal's text."""

import numpy as np

from nlp.data import TAGS, encode
from nlp.decode import decode_fields, merge_chunks

TEXT = "Over 9 months we reach 3,200 students in Gaya for Rs 18 lakh; scores 48% to 57%."


def _spans(text, duration="9"):
    find = lambda s: (text.index(s), text.index(s) + len(s))
    return {"duration": find(duration), "beneficiaries": find("3,200"), "district": find("Gaya"),
            "amount": find("18 lakh"), "baseline": find("48"), "target": find("57")}


def _perfect_scores(chunk):
    """What a perfect model would output: one-hot on the true tag."""
    scores = np.zeros((len(chunk["input_ids"]), len(TAGS)))
    for i, label in enumerate(chunk["labels"]):
        scores[i, 0 if label == -100 else label] = 1.0
    return scores


def _decode(tokenizer, text, spans, **kw):
    chunks = encode(tokenizer, text, spans, **kw)
    offsets, scores = merge_chunks(chunks, [_perfect_scores(c) for c in chunks])
    return decode_fields(text, offsets, scores)


def test_perfect_tags_decode_back_to_every_value(tokenizer):
    fields = _decode(tokenizer, TEXT, _spans(TEXT))
    values = {k: f.value for k, f in fields.items()}
    assert values == {"duration": 9, "beneficiaries": 3200, "district": "Gaya",
                      "amount": 1_800_000, "baseline": 48, "target": 57}
    assert TEXT[fields["amount"].start:fields["amount"].end] == "18 lakh"


def test_a_duration_in_years_is_converted_to_months(tokenizer):
    text = TEXT.replace("Over 9 months", "Over 2 years")
    spans = _spans(text, duration="2")
    assert _decode(tokenizer, text, spans)["duration"].value == 24


def test_a_field_the_text_never_states_comes_back_empty(tokenizer):
    spans = {k: v for k, v in _spans(TEXT).items() if k != "baseline"}
    assert "baseline" not in _decode(tokenizer, TEXT, spans)


def test_when_two_spans_compete_the_more_confident_one_wins(tokenizer):
    [chunk] = encode(tokenizer, TEXT, _spans(TEXT))
    scores = _perfect_scores(chunk)
    # Make "48" a weaker TARGET candidate than "57".
    tokens = tokenizer.convert_ids_to_tokens(chunk["input_ids"])
    i48 = tokens.index("48")
    scores[i48] = 0.0
    scores[i48, TAGS.index("B-TARGET")] = 0.4
    scores[i48, 0] = 0.3
    offsets, merged = merge_chunks([chunk], [scores])
    assert decode_fields(TEXT, offsets, merged)["target"].value == 57


def test_facts_in_the_overlap_of_two_chunks_decode_once_and_correctly(tokenizer):
    filler = "The community has long asked for this support. " * 30
    text = filler + TEXT + " " + filler
    fields = _decode(tokenizer, text, _spans(text), max_length=128, stride=64)
    assert {k: f.value for k, f in fields.items()} == {
        "duration": 9, "beneficiaries": 3200, "district": "Gaya",
        "amount": 1_800_000, "baseline": 48, "target": 57}
