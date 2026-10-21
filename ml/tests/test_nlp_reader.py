"""The reader: three fine-tuned BERTs behind one call. Tested with tiny
randomly initialised BERTs so it runs in seconds, offline."""

import numpy as np
import pytest
import torch
from transformers import BertConfig, BertForSequenceClassification, BertForTokenClassification

from nlp.data import METRIC_LABELS, SDG_LABELS, TAGS, Example
from nlp.decode import Field
from nlp.reader import ProposalReader, Reading, assemble
from nlp.training import field_items, fine_tune, metric_items, sdg_items, tune_threshold

TEXT = ("Asha Trust will run remedial classes in Gaya. We aim to raise attendance from 48% to 57%. "
        "The cost is Rs 18 lakh.")


def _tiny(tokenizer, cls, **kw):
    torch.manual_seed(0)
    config = BertConfig(vocab_size=tokenizer.vocab_size, hidden_size=32, num_hidden_layers=2,
                        num_attention_heads=2, intermediate_size=64, max_position_embeddings=512, **kw)
    return cls(config)


@pytest.fixture(scope="module")
def tiny_reader(tokenizer):
    sdg = _tiny(tokenizer, BertForSequenceClassification, num_labels=len(SDG_LABELS),
                problem_type="multi_label_classification")
    metric = _tiny(tokenizer, BertForSequenceClassification, num_labels=len(METRIC_LABELS))
    fields = _tiny(tokenizer, BertForTokenClassification, num_labels=len(TAGS))
    return ProposalReader(tokenizer, sdg, metric, fields, threshold=0.5, device="cpu")


def _examples():
    def span(s):
        return (TEXT.index(s), TEXT.index(s) + len(s))
    spans = {"baseline": span("48"), "target": span("57"), "amount": span("18 lakh"), "district": span("Gaya")}
    return [Example(i, TEXT, [4], METRIC_LABELS.index("attendance_rate"), spans, "train", "gemini")
            for i in range(4)]


def test_assemble_keeps_confident_sdgs_and_flags_every_missing_field():
    sdg_probs = np.zeros(len(SDG_LABELS))
    sdg_probs[SDG_LABELS.index(4)] = 0.92
    sdg_probs[SDG_LABELS.index(5)] = 0.61
    sdg_probs[SDG_LABELS.index(3)] = 0.20
    metric_probs = np.zeros(len(METRIC_LABELS))
    metric_probs[METRIC_LABELS.index("attendance_rate")] = 0.8
    target_at = TEXT.index("57")
    fields = {"target": Field(57, "57", target_at, target_at + 2, 0.9),
              "district": Field("Gaya", "Gaya", TEXT.index("Gaya"), TEXT.index("Gaya") + 4, 0.9)}
    r = assemble(TEXT, sdg_probs, metric_probs, fields, threshold=0.5)
    assert r.sdgs == [4, 5] and r.sdg_confidence == {"4": 0.92, "5": 0.61}
    assert (r.metric_name, r.metric_unit) == ("attendance_rate", "percentage_points")
    assert r.goal == "We aim to raise attendance from 48% to 57%."
    assert any("baseline" in f for f in r.red_flags) and any("beneficiar" in f for f in r.red_flags)
    assert not any("location" in f for f in r.red_flags)


def test_with_no_confident_sdg_it_keeps_the_best_one_and_says_so():
    sdg_probs = np.full(len(SDG_LABELS), 0.1)
    sdg_probs[SDG_LABELS.index(6)] = 0.3
    r = assemble(TEXT, sdg_probs, np.ones(len(METRIC_LABELS)) / len(METRIC_LABELS), {}, threshold=0.5)
    assert r.sdgs == [6]
    assert any("low confidence" in f for f in r.red_flags)


def test_training_items_cover_every_chunk_with_the_right_targets(tokenizer):
    ex = _examples()
    s, m, f = sdg_items(ex, tokenizer), metric_items(ex, tokenizer), field_items(ex, tokenizer)
    assert len(s) == len(m) == len(f) == 4
    assert s[0]["labels"][SDG_LABELS.index(4)] == 1.0 and sum(s[0]["labels"]) == 1.0
    assert m[0]["labels"] == METRIC_LABELS.index("attendance_rate")
    assert len(f[0]["labels"]) == len(f[0]["input_ids"])


def test_fine_tune_learns_a_handful_of_examples(tokenizer):
    model = _tiny(tokenizer, BertForTokenClassification, num_labels=len(TAGS))
    items = field_items(_examples(), tokenizer)
    history = fine_tune(model, items, items, epochs=40, lr=5e-3, batch_size=4, device="cpu", seed=0,
                        patience=None)
    assert history[-1]["train_loss"] < 0.5 * history[0]["train_loss"]
    # The best epoch by validation loss is the one kept.
    assert history.best_val_loss == pytest.approx(min(h["val_loss"] for h in history))


def test_threshold_is_tuned_for_micro_f1():
    probs = np.array([[0.9, 0.35], [0.6, 0.1], [0.3, 0.7]])
    targets = np.array([[1, 1], [1, 0], [0, 1]])
    # 0.35 is the only cut that keeps every true label and no false one.
    assert tune_threshold(probs, targets) == pytest.approx(0.35)


def test_reader_returns_a_reading_and_survives_save_and_load(tiny_reader, tmp_path):
    first = tiny_reader.read(TEXT)
    assert isinstance(first, Reading) and first.sdgs and first.metric_name in METRIC_LABELS
    tiny_reader.save(tmp_path / "reader")
    again = ProposalReader.load(tmp_path / "reader", device="cpu").read(TEXT)
    assert again == first
