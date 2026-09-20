#!/usr/bin/env python
"""Score the M023 spike field sets with the pinned Cua-S1 checkpoint.

Runs ONLY in the separate Python 3.11 environment (``.venv-cua-s1``) that
has ``cua-s1``, ``torch``, and ``safetensors`` installed:

    PYTHONPATH=src .venv-cua-s1/bin/python scripts/cua_s1_scoring.py \\
        --pin-dir models/cua-s1-forms \\
        --out models/cua-s1-forms/decisions.json

One forward pass per element; writes the pinned decisions document the
stdlib-only provider consumes (version + cases_sha256 + per-element
options/probabilities/argmax + latencies + artifact hashes). No network
access at scoring time; the checkpoint is loaded through the upstream
loader, which validates the JSON sidecar and the state signature.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin-dir", default=str(REPO_ROOT / "models" / "cua-s1-forms"))
    parser.add_argument("--out", default="")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    pin_dir = Path(args.pin_dir)
    weights = pin_dir / "cua-s1-forms.safetensors"
    config_path = pin_dir / "cua-s1-forms.json"
    if not weights.is_file() or not config_path.is_file():
        print("missing checkpoint files in", pin_dir)
        return 1

    from vision_assistant import cua_s1_provider as csp

    import torch
    from cua_s1.model import ChoiceExample, load_checkpoint

    model, collator, config = load_checkpoint(weights, args.device)
    sidecar = json.loads(config_path.read_text(encoding="utf-8"))

    document = {
        "version": csp.DECISION_VERSION,
        "cases_sha256": csp.cases_sha256(),
        "generator": {
            "model": "cua-s1-forms",
            "weights_sha256": _sha256(weights),
            "config_sha256": _sha256(config_path),
            "state_signature": sidecar.get("state_signature"),
            "config": config,
            "device": args.device,
            "torch": torch.__version__,
        },
        "tasks": {},
    }
    latencies: list = []
    for task_id in sorted(csp.TASK_ELEMENTS):
        cases = csp.build_cases(task_id)
        elements_out = []
        for element in cases["elements"]:
            options = element["options"]
            example = ChoiceExample(context=element["context"],
                                    options=tuple(options), label=0)
            started = time.perf_counter()
            with torch.no_grad():
                logits = model(collator([example]))[0]
            probabilities = torch.softmax(logits, dim=-1)[: len(options)]
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            probs = [round(float(value), 6) for value in probabilities]
            argmax = max(range(len(options)), key=lambda index: probs[index])
            latencies.append(elapsed_ms)
            elements_out.append({
                "key": element["key"],
                "options": list(options),
                "probs": probs,
                "argmax": argmax,
                "probability": probs[argmax],
            })
            print("{:<4} {:<18} -> {:<36} p={:.4f} ({:.1f} ms)".format(
                task_id, element["key"], options[argmax], probs[argmax],
                elapsed_ms))
        document["tasks"][task_id] = {
            "form_title": cases["form_title"],
            "entities": cases["entities"],
            "elements": elements_out,
        }
    document["latency_ms"] = {
        "per_element": [round(value, 3) for value in latencies],
        "mean": round(sum(latencies) / len(latencies), 3),
        "max": round(max(latencies), 3),
    }

    out = Path(args.out) if args.out else pin_dir / "decisions.json"
    out.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n",
                   encoding="utf-8")
    print("scored {} elements; mean {:.1f} ms; wrote {}".format(
        len(latencies), document["latency_ms"]["mean"], out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
