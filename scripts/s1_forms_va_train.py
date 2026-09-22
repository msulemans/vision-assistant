#!/usr/bin/env python
"""Fine-tune the released Cua-S1 checkpoint into S1-FORMS-VA (M024).

Loads the released weights through the upstream loader (JSON sidecar +
state-signature validated; pickle rejected), fine-tunes on the generated
corpus (``scripts/s1_forms_va_generate.py``) with the upstream recipe
(AdamW, linear warmup + cosine decay, gradient clipping 1.0, best
validation-NLL selection), and saves a new safetensors + JSON checkpoint
plus a training report. CPU-friendly; deterministic; no network.

Run:

    .venv-cua-s1/bin/python scripts/s1_forms_va_train.py \
        --train runs/s1-forms-va-corpus/train.jsonl \
        --val runs/s1-forms-va-corpus/val.jsonl \
        --out models/s1-forms-va-v1 --epochs 6 --lr 1e-3 --batch 128
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from collections import defaultdict
from pathlib import Path

import torch
from torch.nn import functional as F
from torch.utils.data import DataLoader, Dataset

from cua_s1.model import (ChoiceExample, load_checkpoint, parameter_count,
                          save_checkpoint, select_device, trainable_state,
                          validate_example)


class JsonlChoices(Dataset):
    """Validated JSONL choices with the row's action label retained."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.examples: list = []
        self.actions: list = []
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                payload = json.loads(line)
                self.examples.append(validate_example(payload))
                meta = payload.get("meta") or {}
                self.actions.append(meta.get("action", "fill"))

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, index: int):
        return self.examples[index]


@torch.no_grad()
def evaluate(model, dataset, collator, device, batch_size: int = 256) -> dict:
    model.eval()
    loader = DataLoader(dataset, batch_size=batch_size, collate_fn=collator)
    per_action = defaultdict(lambda: [0, 0])
    nll_total = 0.0
    offset = 0
    start = time.perf_counter()
    for host_batch in loader:
        batch = {key: value.to(device) for key, value in host_batch.items()}
        logits = model(batch)
        nll_total += float(F.cross_entropy(logits, batch["labels"],
                                           reduction="sum"))
        prediction = logits.argmax(-1)
        correct = prediction.eq(batch["labels"])
        for row in range(correct.shape[0]):
            action = dataset.actions[offset + row]
            per_action[action][0] += int(correct[row])
            per_action[action][1] += 1
        offset += correct.shape[0]
    elapsed = max(time.perf_counter() - start, 1e-12)
    return {
        "nll": nll_total / len(dataset),
        "top1": sum(ok for ok, _ in per_action.values()) / len(dataset),
        "examples": len(dataset),
        "per_action": {action: {"acc": ok / total, "n": total}
                       for action, (ok, total) in sorted(per_action.items())},
        "rows_per_second": len(dataset) / elapsed,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _weights_file(path) -> Path:
    """Accept a checkpoint directory or a weights file for hashing."""

    candidate = Path(path)
    if candidate.is_dir():
        candidate = candidate / "model.safetensors"
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init", default=str(
        Path(__file__).resolve().parents[1] / "models" / "cua-s1-forms" /
        "cua-s1-forms.safetensors"))
    parser.add_argument("--train", required=True)
    parser.add_argument("--val", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--batch", type=int, default=128)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = select_device(args.device)

    model, collator, config = load_checkpoint(args.init, device)
    train_set = JsonlChoices(args.train)
    val_set = JsonlChoices(args.val)
    print("fine-tuning {} -> {}: {} train rows, {} val rows".format(
        Path(args.init).name, args.out, len(train_set), len(val_set)))

    generator = torch.Generator()
    generator.manual_seed(args.seed)
    loader = DataLoader(train_set, batch_size=args.batch, shuffle=True,
                        collate_fn=collator, drop_last=False,
                        generator=generator)
    parameters = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=args.lr, weight_decay=1e-2)
    total_steps = args.epochs * len(loader)
    warmup_steps = int(total_steps * 0.05)

    def rate(step: int) -> float:
        if warmup_steps and step < warmup_steps:
            return (step + 1) / warmup_steps
        progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
        return 0.5 * (1 + math.cos(math.pi * min(progress, 1.0)))

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, rate)
    output_dir = Path(args.out)
    best = {"nll": float("inf"), "macro": -1.0}
    best_state = None
    history = []
    started = time.perf_counter()

    for epoch in range(args.epochs):
        model.train()
        total_loss = 0.0
        rows = 0
        for host_batch in loader:
            batch = {key: value.to(device)
                     for key, value in host_batch.items()}
            loss = F.cross_entropy(model(batch), batch["labels"])
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(parameters, 1.0)
            optimizer.step()
            scheduler.step()
            total_loss += float(loss.detach()) * batch["labels"].numel()
            rows += batch["labels"].numel()
        validation = evaluate(model, val_set, collator, device)
        actions = validation["per_action"]
        macro = (sum(stats["acc"] for stats in actions.values())
                 / max(1, len(actions)))
        record = {"epoch": epoch + 1, "train_nll": total_loss / rows,
                  "val_nll": validation["nll"], "val_top1": validation["top1"],
                  "val_macro": macro,
                  "val_rows_per_second": validation["rows_per_second"]}
        history.append(record)
        print(json.dumps(record, sort_keys=True), flush=True)
        save_checkpoint(output_dir, model, config,
                        metadata={"partial": True, "epoch": epoch + 1})
        # Keep the epoch with the best macro per-action accuracy (nll as a
        # tiebreak): every action class matters equally for the gate.
        if (macro, -validation["nll"]) > (best["macro"], -best["nll"]):
            best = {key: value for key, value in validation.items()
                    if key != "rows_per_second"}
            best["macro"] = macro
            best_state = {name: tensor.detach().cpu().clone()
                          for name, tensor in trainable_state(model).items()}

    model.load_state_dict(best_state, strict=False)
    metadata = {
        "task": "s1-forms-va-domain-adaptation",
        "initialized_from": str(args.init),
        "init_sha256": _sha256(_weights_file(args.init)),
        "corpus": {"train": str(args.train), "val": str(args.val),
                   "train_rows": len(train_set), "val_rows": len(val_set)},
        "seed": args.seed, "epochs": args.epochs, "batch_size": args.batch,
        "learning_rate": args.lr, "history": history,
        "best_validation": best,
        "train_seconds": round(time.perf_counter() - started, 3),
    }
    output = Path(args.out)
    save_checkpoint(output, model, config, metadata=metadata)
    report = dict(metadata)
    report["checkpoint"] = str(output)
    report["parameters"] = parameter_count(model)
    report["model_sha256"] = _sha256(output / "model.safetensors")
    (output / "training-report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("best validation:", json.dumps(best, sort_keys=True))
    print("saved:", output, "| train seconds:",
          metadata["train_seconds"], "| params:", report["parameters"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
