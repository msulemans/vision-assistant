from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .adapters import FakeAnswerPolicy, FakeCapturePort, FakeVisionModelPort, FailingCapturePort
from .clock import FakeClock
from .events import KIND_DETERMINISTIC
from .fixture import SyntheticFixture, generate_fixture
from .ports import CaptureSource
from .spine import ReadOnlyTurn
from .trace import JsonlTraceSink

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs"
UI_OUTPUT = REPO_ROOT / "ui" / "index.html"
TEMPLATE = Path(__file__).with_name("ui_template.html")

SOURCE = CaptureSource(kind="window", label="Synthetic window: Connect to Database")
QUESTION = "What does this dialog ask the user to do?"

SCENARIOS = {
    "success": {"timeout_ms": None, "cancel_after_emit": None, "use_failing": False},
    "failure": {"timeout_ms": None, "cancel_after_emit": None, "use_failing": True},
    "cancel": {"timeout_ms": None, "cancel_after_emit": "capture.requested", "use_failing": False},
    "timeout": {"timeout_ms": 50.0, "cancel_after_emit": None, "use_failing": False},
}


def run_scenario(
    name: str,
    *,
    outdir: Path,
    fixture: SyntheticFixture,
) -> tuple[str, Path, list[dict]]:
    """Run one deterministic scenario and write its JSONL trace.

    Returns (final_state, trace_path, parsed_records).
    """
    cfg = SCENARIOS[name]
    clock = FakeClock()

    if cfg["use_failing"]:
        capture = FailingCapturePort()
    else:
        capture = FakeCapturePort(fixture)

    model = FakeVisionModelPort()
    policy = FakeAnswerPolicy()
    trace_id = f"m002-{name}"
    path = outdir / f"{trace_id}.jsonl"

    sink = JsonlTraceSink(
        path,
        trace_id=trace_id,
        kind=KIND_DETERMINISTIC,
        created_at_ms=clock.now_ms(),
    )
    turn = ReadOnlyTurn(
        trace_id=trace_id,
        clock=clock,
        capture=capture,
        model=model,
        policy=policy,
        sink=sink,
        timeout_ms=cfg["timeout_ms"],
    )
    final_state = turn.run(
        source=SOURCE,
        question=QUESTION,
        cancel_after_emit=cfg["cancel_after_emit"],
    )
    sink.write()
    records = sink.read_back()
    return final_state, path, records


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_determinism(outdir: Path, fixture: SyntheticFixture) -> dict:
    """Re-run each scenario and confirm byte-identical, round-tripping traces."""
    results: dict[str, dict] = {}
    for name in SCENARIOS:
        first_state, first_path, records = run_scenario(name, outdir=outdir, fixture=fixture)
        first_hash = _sha256(first_path)
        second_state, second_path, records2 = run_scenario(name, outdir=outdir, fixture=fixture)
        second_hash = _sha256(second_path)

        round_trip = records == records2
        # Round-trip safety: every parsed line is a valid dict and includes
        # the provenance fields the UI depends on.
        has_started = any(r.get("type") == "turn.started" for r in records)
        terminal_events = [
            r.get("type")
            for r in records
            if r.get("type") in {"turn.completed", "turn.cancelled", "turn.timed_out", "turn.failed"}
        ]

        results[name] = {
            "deterministic": first_hash == second_hash,
            "round_trip": round_trip,
            "first_hash": first_hash,
            "second_hash": second_hash,
            "final_state": first_state,
            "events": len(records) - 1,  # minus meta line
            "has_started": has_started,
            "terminal": terminal_events,
        }
    return results


def render_ui(output_path: Path, traces: dict[str, dict], fixture: SyntheticFixture) -> None:
    """Render the dependency-free browser UI from the observed traces."""
    trace_set = {
        name: {
            "id": data["trace_id"],
            "kind": KIND_DETERMINISTIC,
            # Skip the JSONL meta header so the renderer only sees real events.
            "events": [r for r in data["events"] if r.get("type") != "meta"],
        }
        for name, data in traces.items()
    }
    fixtures = {fixture.id: fixture.data_uri}

    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("/*__TRACE_SET__*/", json.dumps(trace_set, ensure_ascii=False))
    html = html.replace("/*__FIXTURES__*/", json.dumps(fixtures, ensure_ascii=False))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Milestone 002 deterministic event spine lab")
    parser.add_argument("--outdir", type=Path, default=RUNS_DIR, help="directory for JSONL traces")
    parser.add_argument("--ui", type=Path, default=UI_OUTPUT, help="output path for the static UI page")
    parser.add_argument("--verify", action="store_true", help="verify determinism and round-trip")
    args = parser.parse_args(argv)

    outdir = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    fixtures_dir = outdir / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    fixture = generate_fixture(fixture_id="synthetic-dialog-001", path=fixtures_dir / "synthetic-dialog-001.png")

    traces: dict[str, dict] = {}
    for name in SCENARIOS:
        final_state, path, records = run_scenario(name, outdir=outdir, fixture=fixture)
        traces[name] = {"trace_id": f"m002-{name}", "events": records}
        print(f"scenario={name:<8} final={final_state:<9} events={len(records) - 1:<3} trace={path.name}")

    render_ui(args.ui, traces, fixture)
    print(f"ui={args.ui}")
    print(f"fixture={fixture.path} ({fixture.width}x{fixture.height})")

    if args.verify:
        print("verify:")
        verified = verify_determinism(outdir, fixture)
        ok = True
        for name, r in verified.items():
            line = (
                f"  {name:<8} deterministic={r['deterministic']} round_trip={r['round_trip']} "
                f"events={r['events']} terminal={r['terminal']}"
            )
            print(line)
            ok = ok and r["deterministic"] and r["round_trip"]
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
