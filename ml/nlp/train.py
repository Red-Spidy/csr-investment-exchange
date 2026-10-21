"""Fine-tune and evaluate the three BERT readers.

    PYTHONPATH=ml .venv/bin/python -m nlp.train [--train-providers gemini]
    -> ml/artifacts/bert/ (the reader), ml/results/nlp_metrics.json

Protocol, so the test numbers mean something:
  1. Fine-tune each reader on TRAIN; keep the epoch with the lowest VAL loss.
  2. Tune the SDG threshold on VAL.
  3. Score TEST once -- proposals from NGOs no reader has seen.

Reported next to the rule baseline, and split by which LLM wrote the text.
With --train-providers, training uses only those writers, so a writer left
out becomes an unseen-style test: does BERT read content, or one model's habits?
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from transformers import AutoModelForSequenceClassification, AutoModelForTokenClassification, AutoTokenizer

from nlp.baseline import rule_read
from nlp.data import METRIC_LABELS, SDG_LABELS, TAGS, build_examples, sdg_vector
from nlp.evaluate import evaluate, reading_to_prediction
from nlp.reader import MODEL_VERSION, ProposalReader
from nlp.training import DEVICE, field_items, fine_tune, metric_items, sdg_items, tune_threshold
from synth.build import load_world

BASE_MODEL = "bert-base-cased"
DATASETS = Path("ml/datasets")
PROPOSALS = DATASETS / "proposals.jsonl"
ARTIFACT = Path("ml/artifacts/bert")
RESULTS = Path("ml/results/nlp_metrics.json")
EPOCHS, LEARNING_RATE, BATCH_SIZE, SEED = 6, 3e-5, 8, 0


def _summary(name: str, r: dict) -> str:
    f = r["fields"]
    return (f"{name:28} n={r['n']:<4} SDG micro-F1 {r['sdg']['micro_f1']:.3f}  macro-F1 {r['sdg']['macro_f1']:.3f}  "
            f"metric acc {r['metric_accuracy']:.3f}  fields acc {f['accuracy_on_stated']:.3f}  "
            f"hallucination {f['hallucination_rate']:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--train-providers", nargs="*", default=None,
                        help="train only on proposals written by these providers")
    args = parser.parse_args()

    world = load_world(DATASETS)
    proposals = [json.loads(line) for line in PROPOSALS.read_text().splitlines() if line.strip()]
    examples = build_examples(proposals, world.projects)
    split = {s: [e for e in examples if e.split == s] for s in ("train", "val", "test")}
    if args.train_providers:
        for s in ("train", "val"):
            split[s] = [e for e in split[s] if e.provider in args.train_providers]
    print(f"device {DEVICE} | train {len(split['train'])}  val {len(split['val'])}  test {len(split['test'])}")

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    pad = tokenizer.pad_token_id
    sdg = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL, num_labels=len(SDG_LABELS), problem_type="multi_label_classification")
    metric = AutoModelForSequenceClassification.from_pretrained(BASE_MODEL, num_labels=len(METRIC_LABELS))
    fields = AutoModelForTokenClassification.from_pretrained(
        BASE_MODEL, num_labels=len(TAGS), id2label=dict(enumerate(TAGS)), label2id={t: i for i, t in enumerate(TAGS)})

    histories = {}
    for name, model, items in (("sdg", sdg, sdg_items), ("metric", metric, metric_items), ("fields", fields, field_items)):
        print(f"fine-tuning {name} reader")
        history = fine_tune(model, items(split["train"], tokenizer), items(split["val"], tokenizer),
                            epochs=EPOCHS, lr=LEARNING_RATE, batch_size=BATCH_SIZE, seed=SEED, pad_id=pad, log=print)
        histories[name] = {"epochs": list(history), "best_val_loss": history.best_val_loss}

    reader = ProposalReader(tokenizer, sdg, metric, fields)
    val_probs = np.array([reader.scores(e.text)[0] for e in split["val"]])
    reader.threshold = tune_threshold(val_probs, np.array([sdg_vector(e.sdgs) for e in split["val"]]))
    reader.save(ARTIFACT)

    projects = world.projects.set_index("project_id")
    bert = lambda text: reading_to_prediction(reader.read(text))
    results = {"bert": evaluate(bert, split["test"], projects),
               "rule_baseline": evaluate(rule_read, split["test"], projects)}
    for provider in sorted({e.provider for e in split["test"]}):
        subset = [e for e in split["test"] if e.provider == provider]
        results[f"bert_written_by_{provider}"] = evaluate(bert, subset, projects)

    report = {
        "model_version": MODEL_VERSION,
        "base_model": BASE_MODEL,
        "protocol": "fit on train, best epoch by val loss, SDG threshold tuned on val, test scored once",
        "train_providers": args.train_providers or "all",
        "sdg_threshold": reader.threshold,
        "sizes": {s: len(v) for s, v in split.items()},
        "training": histories,
        "test": results,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"\nSDG threshold {reader.threshold}")
    for name, r in results.items():
        print(_summary(name, r))
    print(f"saved {ARTIFACT}, {RESULTS}")


if __name__ == "__main__":
    main()
