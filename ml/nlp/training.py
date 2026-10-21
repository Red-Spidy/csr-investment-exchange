"""Fine-tuning for the three readers: one plain PyTorch loop, no extra libraries.

Every chunk of a proposal is one training item. SDG and metric targets are the
proposal's; token targets come from the checker's spans. The epoch with the
lowest validation loss is the one kept.
"""

from __future__ import annotations

import math

import numpy as np
import torch
from transformers import get_linear_schedule_with_warmup

from nlp.data import IGNORE, encode, sdg_vector

DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"


class History(list):
    best_val_loss: float = float("inf")


def sdg_items(examples, tokenizer) -> list[dict]:
    return [{"input_ids": c["input_ids"], "attention_mask": c["attention_mask"], "labels": sdg_vector(ex.sdgs)}
            for ex in examples for c in encode(tokenizer, ex.text)]


def metric_items(examples, tokenizer) -> list[dict]:
    return [{"input_ids": c["input_ids"], "attention_mask": c["attention_mask"], "labels": ex.metric}
            for ex in examples for c in encode(tokenizer, ex.text)]


def field_items(examples, tokenizer) -> list[dict]:
    return [{"input_ids": c["input_ids"], "attention_mask": c["attention_mask"], "labels": c["labels"]}
            for ex in examples for c in encode(tokenizer, ex.text, ex.spans)]


def collate(items: list[dict], pad_id: int = 0) -> dict[str, torch.Tensor]:
    """Pad a batch. Token labels pad with IGNORE so padding never counts."""
    width = max(len(i["input_ids"]) for i in items)
    batch = {
        "input_ids": torch.tensor([i["input_ids"] + [pad_id] * (width - len(i["input_ids"])) for i in items]),
        "attention_mask": torch.tensor([i["attention_mask"] + [0] * (width - len(i["attention_mask"])) for i in items]),
    }
    if "labels" in items[0]:
        first = items[0]["labels"]
        if isinstance(first, int):                                   # metric: one class
            batch["labels"] = torch.tensor([i["labels"] for i in items])
        elif isinstance(first[0], float):                            # SDGs: multi-hot
            batch["labels"] = torch.tensor([i["labels"] for i in items], dtype=torch.float)
        else:                                                        # fields: one tag per token
            batch["labels"] = torch.tensor([i["labels"] + [IGNORE] * (width - len(i["labels"])) for i in items])
    return batch


@torch.no_grad()
def _mean_loss(model, items, batch_size, device, pad_id) -> float:
    model.eval()
    total = 0.0
    for start in range(0, len(items), batch_size):
        chunk = items[start:start + batch_size]
        batch = {k: v.to(device) for k, v in collate(chunk, pad_id).items()}
        total += model(**batch).loss.item() * len(chunk)
    return total / len(items)


def fine_tune(model, train_items, val_items, *, epochs: int = 4, lr: float = 3e-5, batch_size: int = 8,
              device: str = DEVICE, seed: int = 0, patience: int | None = 2, pad_id: int = 0,
              log=lambda msg: None) -> History:
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model.to(device)
    optimiser = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    total_steps = epochs * math.ceil(len(train_items) / batch_size)
    schedule = get_linear_schedule_with_warmup(optimiser, int(0.1 * total_steps), total_steps)

    history, best_state, stale = History(), None, 0
    for epoch in range(epochs):
        model.train()
        order = rng.permutation(len(train_items))
        running = 0.0
        for start in range(0, len(order), batch_size):
            chunk = [train_items[i] for i in order[start:start + batch_size]]
            batch = {k: v.to(device) for k, v in collate(chunk, pad_id).items()}
            loss = model(**batch).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimiser.step()
            schedule.step()
            optimiser.zero_grad()
            running += loss.item() * len(chunk)
        val_loss = _mean_loss(model, val_items, batch_size, device, pad_id)
        history.append({"epoch": epoch + 1, "train_loss": running / len(train_items), "val_loss": val_loss})
        log(f"  epoch {epoch + 1}: train {history[-1]['train_loss']:.4f}  val {val_loss:.4f}")
        if val_loss < history.best_val_loss:
            history.best_val_loss = val_loss
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if patience is not None and stale >= patience:
                break
    model.load_state_dict(best_state)
    return history


def tune_threshold(probs: np.ndarray, targets: np.ndarray) -> float:
    """SDG decision threshold with the best micro-F1 on validation data."""
    best_t, best_f1 = 0.5, -1.0
    for t in np.round(np.arange(0.05, 0.96, 0.05), 2):
        pred = probs >= t
        tp = float((pred & (targets == 1)).sum())
        fp = float((pred & (targets == 0)).sum())
        fn = float((~pred & (targets == 1)).sum())
        f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
        if f1 > best_f1:
            best_t, best_f1 = float(t), f1
    return best_t
