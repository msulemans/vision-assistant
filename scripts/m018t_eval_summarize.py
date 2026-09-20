"""Summarize the M018T evaluation batches into one evidence JSON.

Usage:
    python scripts/m018t_eval_summarize.py <baseline-dir> <treatment-dir>

Reads the two ``m018t-eval-*`` run directories (paired screenshot baseline and
target treatment over the same frozen 20 tasks) and writes
``docs/evidence/2026-09-20-m018t-eval.json`` with per-task rows, productive
counts, refusal outcomes, and Wilson 95% intervals. No tuning, no reruns —
this only formats what ran.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REFUSAL_IDS = ("t19", "t20")
OUT = Path("docs/evidence/2026-09-20-m018t-eval.json")


def wilson(successes: int, total: int, z: float = 1.96):
    if total == 0:
        return [0.0, 0.0]
    phat = successes / total
    denom = 1 + z * z / total
    center = (phat + z * z / (2 * total)) / denom
    half = (z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
            / denom)
    return [round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)]


def load_batch(root: Path) -> dict:
    summary = json.loads((root / "loop-summary.json").read_text(encoding="utf-8"))
    rows = []
    for task_file in sorted(root.glob("task-*.json")):
        report = json.loads(task_file.read_text(encoding="utf-8"))
        rows.append({
            "task": report["task"],
            "outcome": report["outcome"],
            "oracle_ok": bool(report.get("oracle", {}).get("ok")),
            "failures": report.get("oracle", {}).get("failures", []),
            "calls": report["calls"],
            "actions": report["actions"],
            "ms": report["elapsed_ms"],
            "refusals": [row["refused"] for row in report["steps"]
                         if row.get("refused")],
        })
    productive = [row for row in rows if row["task"] not in REFUSAL_IDS]
    refusals = [row for row in rows if row["task"] in REFUSAL_IDS]
    productive_ok = sum(1 for row in productive if row["oracle_ok"])
    refusal_ok = sum(1 for row in refusals if row["oracle_ok"])
    return {
        "dir": str(root),
        "stage": summary.get("stage"),
        "mode": summary.get("mode"),
        "ids": summary.get("ids"),
        "productive_ok": productive_ok,
        "productive_total": len(productive),
        "productive_wilson95": wilson(productive_ok, len(productive)),
        "refusal_ok": refusal_ok,
        "refusal_total": len(refusals),
        "password_refusal_events": sum(
            1 for row in rows for reason in row["refusals"]
            if reason == "refused_password"),
        "rows": rows,
    }


def main(argv) -> int:
    baseline_dir = Path(argv[1])
    treatment_dir = Path(argv[2])
    payload = {
        "stage": "M018T-EVAL",
        "date": "2026-09-20",
        "set": {"tasks": 20, "productive": 18, "refusals": 2,
                "freeze": "docs/M018T_EVAL_FREEZE.md"},
        "baseline_screenshot": load_batch(baseline_dir),
        "treatment_target": load_batch(treatment_dir),
        "comparison": {
            "paired_productive_delta": (
                load_batch(treatment_dir)["productive_ok"]
                - load_batch(baseline_dir)["productive_ok"]),
            "m018d_reference": {
                "dev": "4/30 productive (m018d-v3, screenshot mode)",
                "heldout": "3/18 productive (m018d-v3, screenshot mode)",
                "note": ("Rate-vs-rate on disjoint sets only; the paired "
                         "within-set comparison above is the primary contrast."),
            },
        },
    }
    OUT.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n",
                   encoding="utf-8")
    b = payload["baseline_screenshot"]
    t = payload["treatment_target"]
    print("baseline : {}/{} productive (Wilson {}), refusals {}/{}".format(
        b["productive_ok"], b["productive_total"], b["productive_wilson95"],
        b["refusal_ok"], b["refusal_total"]))
    print("treatment: {}/{} productive (Wilson {}), refusals {}/{}".format(
        t["productive_ok"], t["productive_total"], t["productive_wilson95"],
        t["refusal_ok"], t["refusal_total"]))
    print("written:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
