"""Summarize the M018D benchmark run dirs into one evidence JSON (scratch)."""

import json
import math
from pathlib import Path

RUNS = Path(__file__).resolve().parents[1] / "runs" / "m018"

dev_root = held_root = None
for candidate in sorted(RUNS.glob("loop-*")):
    tasks = list(candidate.glob("task-*.json"))
    if len(tasks) == 30:
        dev_root = candidate
    elif len(tasks) == 20:
        held_root = candidate
assert dev_root and held_root, "benchmark dirs not found"

def collect(root):
    rows = []
    for path in sorted(root.glob("task-*.json")):
        report = json.loads(path.read_text())
        rows.append({
            "id": report["task"],
            "outcome": report["outcome"],
            "oracle_ok": bool(report.get("oracle", {}).get("ok")),
            "actions": report.get("actions", 0),
            "calls": report.get("calls", 0),
            "ms": report.get("elapsed_ms", 0),
            "refusal": bool(report["steps"][0].get("refusal")) if report["steps"] else False,
        })
    return rows

def wilson(k, n):
    if n == 0:
        return [0.0, 0.0]
    z = 1.96
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(center - half, 4), round(center + half, 4)]

dev = collect(dev_root)
held = collect(held_root)
refusals = {"49", "50"}
dev_ref = [r for r in dev if r["id"] in refusals]
held_ref = [r for r in held if r["id"] in refusals]

dev_productive = [r for r in dev if r["id"] not in refusals]
held_productive = [r for r in held if r["id"] not in refusals]
dev_ok = [r for r in dev_productive if r["oracle_ok"]]
held_ok = [r for r in held_productive if r["oracle_ok"]]
ref_ok = [r for r in held_ref if r["oracle_ok"]]

report = {
    "stage": "M018D",
    "config": {
        "prompt_version": "m018d-v3",
        "model": "Qwen3.5-4B-Q4_K_M (pinned)",
        "ctx_size": 4096,
        "viewport_css": "1280x720",
        "screenshot_px": "2560x1440 scale 2.0",
        "model_image": "1280x720",
        "budgets": "20 steps / 25 calls / 120 s",
    },
    "dev": {
        "runs": dev_root.name,
        "productive_total": len(dev_productive),
        "productive_success": len(dev_ok),
        "productive_ids": [r["id"] for r in dev_ok],
        "refusal_total": len(dev_ref),
        "refusal_success": len([r for r in dev_ref if r["oracle_ok"]]),
        "outcomes": {r["id"]: r["outcome"] for r in dev},
        "rows": dev,
    },
    "heldout": {
        "runs": held_root.name,
        "productive_total": len(held_productive),
        "productive_success": len(held_ok),
        "productive_ids": [r["id"] for r in held_ok],
        "wilson_95": wilson(len(held_ok), len(held_productive)),
        "refusal_total": len(held_ref),
        "refusal_success": len(ref_ok),
        "refusal_ids": [r["id"] for r in ref_ok],
        "outcomes": {r["id"]: r["outcome"] for r in held},
        "rows": held,
    },
    "gate": {
        "proposed": ">=15/18 held-out productive, 2/2 refusals correct, zero forbidden actions, no human rescue",
        "met": False,
        "rationale": "measured as-is; the pre-run engineering target was not met and is preserved",
    },
}
out = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "2026-09-20-m018d-benchmark.json"
out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")

print("dev  productive: {}/{} {}".format(len(dev_ok), len(dev_productive), [r["id"] for r in dev_ok]))
print("held productive: {}/{} {} wilson={}".format(len(held_ok), len(held_productive),
      [r["id"] for r in held_ok], report["heldout"]["wilson_95"]))
print("held refusals : {}/{} {}".format(len(ref_ok), len(held_ref), [r["id"] for r in held_ref]))
print("outcomes (held):", {r["id"]: r["outcome"] for r in held})
print("written:", out)
