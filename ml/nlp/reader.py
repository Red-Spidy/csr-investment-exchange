"""Read one NGO proposal with the three fine-tuned BERTs.

    reader = ProposalReader.load("ml/artifacts/bert")
    reading = reader.read(proposal_text)

A reading carries SDGs with confidences, the outcome metric being claimed,
every field the text states (with where it says it), the goal sentence, and
red flags. A field the text does not state is absent and flagged -- the
pipeline routes such projects to a person rather than guess a number that
would flow into the impact forecast and a funding decision.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoModelForTokenClassification, AutoTokenizer

from nlp.data import METRIC_LABELS, METRIC_UNITS, SDG_LABELS, encode
from nlp.decode import Field, decode_fields, merge_chunks
from nlp.training import DEVICE, collate

MODEL_VERSION = "bert-v1"

MISSING_FIELD_FLAGS = {
    "baseline": "no baseline stated, so the improvement cannot be measured",
    "target": "no measurable target stated",
    "beneficiaries": "no beneficiary count stated",
    "amount": "requested amount not found in the text",
    "duration": "project duration not stated",
    "district": "location not stated",
}
LOW_SDG_CONFIDENCE = "low confidence in the SDG classification"


@dataclass(frozen=True)
class Reading:
    sdgs: list[int]
    sdg_confidence: dict[str, float]
    metric_name: str
    metric_unit: str
    metric_confidence: float
    fields: dict[str, Field]
    goal: str | None
    red_flags: list[str] = field(default_factory=list)


def _sentence_at(text: str, position: int) -> str:
    """The sentence containing `position`. A period ends a sentence only when
    whitespace follows, so '12.6 lakh' is not split."""
    bounds = [m.end() for m in re.finditer(r"[.!?](?=\s)|\n", text)]
    start = max((b for b in bounds if b <= position), default=0)
    end = min((b for b in bounds if b > position), default=len(text))
    return text[start:end].strip()


def assemble(text: str, sdg_probs, metric_probs, fields: dict[str, Field], threshold: float) -> Reading:
    sdg_probs, metric_probs = np.asarray(sdg_probs, dtype=float), np.asarray(metric_probs, dtype=float)
    flags = [message for name, message in MISSING_FIELD_FLAGS.items() if name not in fields]

    chosen = [g for g, p in zip(SDG_LABELS, sdg_probs) if p >= threshold]
    if not chosen:
        # Every project serves some goal; keep the likeliest, but say we are unsure.
        chosen = [SDG_LABELS[int(np.argmax(sdg_probs))]]
        flags.append(LOW_SDG_CONFIDENCE)

    best_metric = int(np.argmax(metric_probs))
    name = METRIC_LABELS[best_metric]
    return Reading(
        sdgs=chosen,
        sdg_confidence={str(g): round(float(sdg_probs[SDG_LABELS.index(g)]), 4) for g in chosen},
        metric_name=name,
        metric_unit=METRIC_UNITS[name],
        metric_confidence=round(float(metric_probs[best_metric]), 4),
        fields=fields,
        goal=_sentence_at(text, fields["target"].start) if "target" in fields else None,
        red_flags=flags,
    )


class ProposalReader:
    def __init__(self, tokenizer, sdg_model, metric_model, field_model, threshold: float = 0.5,
                 device: str = DEVICE):
        self.tokenizer, self.threshold, self.device = tokenizer, threshold, device
        self.sdg_model = sdg_model.to(device).eval()
        self.metric_model = metric_model.to(device).eval()
        self.field_model = field_model.to(device).eval()

    def read(self, text: str) -> Reading:
        return assemble(text, *self.scores(text), self.threshold)

    @torch.no_grad()
    def scores(self, text: str):
        """Raw model outputs: SDG probabilities, metric probabilities, fields.
        Separate from read() so the SDG threshold can be tuned on them."""
        chunks = encode(self.tokenizer, text)
        items = [{"input_ids": c["input_ids"], "attention_mask": c["attention_mask"]} for c in chunks]
        batch = {k: v.to(self.device) for k, v in collate(items, self.tokenizer.pad_token_id).items()}

        # A goal served anywhere in the proposal counts: max over chunks.
        sdg = torch.sigmoid(self.sdg_model(**batch).logits).max(dim=0).values.cpu().numpy()
        metric = torch.softmax(self.metric_model(**batch).logits.mean(dim=0), dim=-1).cpu().numpy()
        token_probs = torch.softmax(self.field_model(**batch).logits, dim=-1).cpu().numpy()
        per_chunk = [token_probs[i, :len(c["input_ids"])] for i, c in enumerate(chunks)]
        offsets, merged = merge_chunks(chunks, per_chunk)
        return sdg, metric, decode_fields(text, offsets, merged)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        self.tokenizer.save_pretrained(path / "tokenizer")
        self.sdg_model.save_pretrained(path / "sdg")
        self.metric_model.save_pretrained(path / "metric")
        self.field_model.save_pretrained(path / "fields")
        (path / "reader.json").write_text(json.dumps({
            "model_version": MODEL_VERSION,
            "threshold": self.threshold,
            "sdg_labels": list(SDG_LABELS),
            "metric_labels": list(METRIC_LABELS),
        }, indent=2) + "\n")

    @classmethod
    def load(cls, path: Path, device: str = DEVICE) -> ProposalReader:
        path = Path(path)
        meta = json.loads((path / "reader.json").read_text())
        if meta["sdg_labels"] != list(SDG_LABELS) or meta["metric_labels"] != list(METRIC_LABELS):
            raise ValueError(f"{path} was trained on a different label set; retrain it")
        return cls(
            AutoTokenizer.from_pretrained(path / "tokenizer"),
            AutoModelForSequenceClassification.from_pretrained(path / "sdg"),
            AutoModelForSequenceClassification.from_pretrained(path / "metric"),
            AutoModelForTokenClassification.from_pretrained(path / "fields"),
            threshold=meta["threshold"], device=device,
        )
