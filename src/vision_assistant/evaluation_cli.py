"""M016 evaluation CLI: walk a trace, browse the failure catalog and the
model comparison, print reproduction commands and teach-back tasks, or
regenerate the learning site's data file.

    PYTHONPATH=src python -m vision_assistant.evaluation_cli trace --trace learning/data/canonical-turn.jsonl
    PYTHONPATH=src python -m vision_assistant.evaluation_cli failures
    PYTHONPATH=src python -m vision_assistant.evaluation_cli commands
    PYTHONPATH=src python -m vision_assistant.evaluation_cli teachback
    PYTHONPATH=src python -m vision_assistant.evaluation_cli generate
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .evaluation import (
    DEFAULT_TRACE,
    FAILURE_CATALOG,
    REPRODUCTION_COMMANDS,
    TEACH_BACK_TASKS,
    ascii_waterfall,
    generate_site_data,
    latency_waterfall,
    load_trace,
)


def cmd_trace(args: argparse.Namespace) -> int:
    try:
        waterfall = latency_waterfall(load_trace(args.trace))
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}))
        return 1
    if args.json:
        print(json.dumps(waterfall, indent=2, sort_keys=True))
    else:
        print(ascii_waterfall(waterfall))
    return 0


def cmd_failures(args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps([dict(entry) for entry in FAILURE_CATALOG], indent=2, sort_keys=True))
        return 0
    for entry in FAILURE_CATALOG:
        print(f"[{entry['status']:>16s}] {entry['id']}  ({entry['milestone']})")
        print(f"    {entry['title']}")
        print(f"    cause: {entry['cause']}")
        print(f"    fix:   {entry['fix']}")
    print(f"{len(FAILURE_CATALOG)} entries")
    return 0


def cmd_commands(args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps([dict(entry) for entry in REPRODUCTION_COMMANDS], indent=2, sort_keys=True))
        return 0
    for entry in REPRODUCTION_COMMANDS:
        model = "model" if entry["needs_model"] else "no model"
        print(f"{entry['milestone']}  [{entry['speed']}, {model}] {entry['what']}")
        print(f"    {entry['command']}")
    return 0


def cmd_teachback(args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps([dict(entry) for entry in TEACH_BACK_TASKS], indent=2, sort_keys=True))
        return 0
    for index, task in enumerate(TEACH_BACK_TASKS, 1):
        print(f"{index}. {task['title']}  (gate: {task['gate_item']})")
        print(f"   {task['prompt']}")
        print(f"   where: {task['where']}")
        for point in task["checklist"]:
            print(f"     - {point}")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    out = generate_site_data(args.out, trace_path=args.trace)
    print(json.dumps({"status": "ok", "out": str(out), "trace": str(args.trace)}, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vision_assistant.evaluation_cli",
        description="M016 evaluation: waterfall, failures, commands, teach-back, generate",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    trace = sub.add_parser("trace", help="latency waterfall for one JSONL trace")
    trace.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    trace.add_argument("--json", action="store_true")
    trace.set_defaults(func=cmd_trace)

    failures = sub.add_parser("failures", help="the honest failure catalog")
    failures.add_argument("--json", action="store_true")
    failures.set_defaults(func=cmd_failures)

    commands = sub.add_parser("commands", help="exact reproduction commands per milestone")
    commands.add_argument("--json", action="store_true")
    commands.set_defaults(func=cmd_commands)

    teachback = sub.add_parser("teachback", help="the five gate teach-back tasks")
    teachback.add_argument("--json", action="store_true")
    teachback.set_defaults(func=cmd_teachback)

    generate = sub.add_parser("generate", help="regenerate learning/eval_data.js")
    generate.add_argument("--out", type=Path, default=None)
    generate.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    generate.set_defaults(func=cmd_generate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
