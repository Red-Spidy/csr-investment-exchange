"""Turning proposals into BERT inputs: SDG targets, metric classes, and
token-level field labels aligned from the checker's character spans."""

import pandas as pd
import pytest

from nlp.data import ENTITY_TYPES, METRIC_LABELS, SDG_LABELS, TAGS, build_examples, encode, sdg_vector

TEXT = "Over 9 months we reach 3,200 students in Gaya for Rs 18 lakh; scores 48% to 57%."


def _spans(text):
    find = lambda s: (text.index(s), text.index(s) + len(s))
    return {"duration": find("9"), "beneficiaries": find("3,200"), "district": find("Gaya"),
            "amount": find("18 lakh"), "baseline": find("48"), "target": find("57")}


def _tagged(tokenizer, chunk):
    tokens = tokenizer.convert_ids_to_tokens(chunk["input_ids"])
    return [(t, TAGS[l]) for t, l in zip(tokens, chunk["labels"]) if l != -100]


def test_sdg_targets_are_multi_hot_over_the_sdgs_that_occur():
    assert SDG_LABELS == (1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15)
    v = sdg_vector([2, 4])
    assert v[SDG_LABELS.index(2)] == 1.0 and v[SDG_LABELS.index(4)] == 1.0 and sum(v) == 2.0


def test_every_field_type_has_begin_and_inside_tags():
    assert TAGS[0] == "O"
    for ent in ENTITY_TYPES:
        assert f"B-{ent}" in TAGS and f"I-{ent}" in TAGS


def test_character_spans_become_begin_inside_outside_token_tags(tokenizer):
    [chunk] = encode(tokenizer, TEXT, _spans(TEXT))
    tagged = _tagged(tokenizer, chunk)
    assert ("3", "B-BENEFICIARIES") in tagged and (",", "I-BENEFICIARIES") in tagged
    assert ("200", "I-BENEFICIARIES") in tagged
    assert ("gay", "B-DISTRICT") in tagged and ("##a", "I-DISTRICT") in tagged
    assert ("18", "B-AMOUNT") in tagged and ("##kh", "I-AMOUNT") in tagged
    assert ("48", "B-BASELINE") in tagged and ("57", "B-TARGET") in tagged
    assert ("students", "O") in tagged and ("%", "O") in tagged
    # Special tokens are excluded from the loss.
    assert chunk["labels"][0] == -100 and chunk["labels"][-1] == -100


def test_text_without_spans_gets_no_token_labels(tokenizer):
    [chunk] = encode(tokenizer, TEXT)
    assert chunk["labels"] is None and len(chunk["offsets"]) == len(chunk["input_ids"])


def test_long_proposals_are_split_into_overlapping_chunks_that_keep_every_fact(tokenizer):
    filler = "The community has long asked for this support. " * 60
    text = filler + TEXT + " " + filler
    chunks = encode(tokenizer, text, _spans(text), max_length=128, stride=32)
    assert len(chunks) > 2
    assert all(len(c["input_ids"]) <= 128 for c in chunks)
    for ent in ENTITY_TYPES:
        # Each fact is fully labelled in at least one chunk.
        assert any(f"B-{ent}" in [TAGS[l] for l in c["labels"] if l != -100] for c in chunks), ent


def test_examples_join_text_with_labels_and_inherit_the_project_split():
    proposals = [{"project_id": 2, "text": "t2", "spans": {"target": [0, 1]}, "provider": "gemini"},
                 {"project_id": 1, "text": "t1", "spans": {}, "provider": "groq"}]
    projects = pd.DataFrame({"project_id": [1, 2], "sdgs": [[3], [4, 5]],
                             "metric_name": ["antenatal_coverage", "attendance_rate"],
                             "split": ["test", "train"]})
    examples = {e.project_id: e for e in build_examples(proposals, projects)}
    assert examples[2].sdgs == [4, 5] and examples[2].split == "train" and examples[2].spans == {"target": (0, 1)}
    assert examples[1].metric == METRIC_LABELS.index("antenatal_coverage") and examples[1].provider == "groq"
