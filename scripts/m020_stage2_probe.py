"""M020 Stage 2 probe: one bounded model call proving the pinned runtime
accepts the exact per-action schema and that the reply is exactly one branch.

Exactly ONE model call. ``require_schema=True``: a rejected schema request is
fatal and never silently falls back. Run once; if it fails, record it and
stop (no retries).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from vision_assistant import browser_agent as agent  # noqa: E402
from vision_assistant import browser_targets as targets_mod  # noqa: E402
from vision_assistant import browser_tasks as tasks  # noqa: E402
from vision_assistant import browser_fixtures as fixtures  # noqa: E402
from vision_assistant.browser_session import BrowserSession, compile_helper  # noqa: E402
from vision_assistant.fixture_server import FixtureServer  # noqa: E402
from vision_assistant.runtime_llamaserver import LlamaServerAdapter  # noqa: E402

PROBE_GOAL = "Enter hello into the search query preference field on this page."
PROBE_PAGE = "/prefs/"
PROBE_MODE = "form"
BRANCH_FIELDS = ("target_ref", "observation_id", "text", "option", "value",
                 "answer", "reason", "direction", "amount", "seconds",
                 "expected_change")


def main() -> int:
    parser = argparse.ArgumentParser(description="M020 Stage 2 bounded probe")
    parser.add_argument("--out", default="")
    parser.add_argument("--pin-dir",
                        default=str(REPO_ROOT / "models" / "qwen3.5-4b"))
    parser.add_argument("--ctx-size", type=int, default=4096)
    args = parser.parse_args()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else REPO_ROOT / "runs" / "m018" / (
        "m020-stage2-" + stamp)
    out.mkdir(parents=True, exist_ok=True)

    probe = {
        "stage": "M020-S2", "goal": PROBE_GOAL, "page": PROBE_PAGE,
        "mode": PROBE_MODE, "require_schema": True,
        "model_calls": 0, "generations": 0, "schema_events": [],
        "fallbacks": 0, "raw_reply": None, "raw_keys": [],
        "branch_matches": 0, "matched_branch": None,
        "cross_talk_fields": [], "validator": None,
        "verdict": "BLOCKED", "error": None,
    }

    site = out / "site"
    fixtures.build_site("dev", site)
    server = FixtureServer("dev", site)
    port = server.start()
    helper_bin = compile_helper()

    pin_dir = Path(args.pin_dir)
    pin = json.loads((pin_dir / "pin.json").read_text(encoding="utf-8"))
    model = next(f for f in pin["files"] if f["role"] == "model")
    mmproj = next(f for f in pin["files"] if f["role"] == "mmproj")
    adapter = LlamaServerAdapter(
        pin_dir / model["name"], pin_dir / mmproj["name"],
        ctx_size=args.ctx_size, jinja=True,
        chat_template_kwargs={"enable_thinking": False},
        log_path=out / "server.log")
    session = BrowserSession(port=port, helper_bin=helper_bin,
                             snapshot_dir=out / "shots")
    events: list = []

    try:
        session.launch()
        session.navigate(PROBE_PAGE)
        time.sleep(0.6)
        shot = session.snapshot()
        observed = session.targets()
        shot_bytes = Path(shot.path).read_bytes()
        model_bytes = agent.fit_for_model(shot_bytes)
        model_w, model_h = agent._png_dims(model_bytes)
        observation_id = "obs-{}".format(observed.seq)
        target_block = targets_mod.render_typed_target_block(
            observed.targets, model_w, model_h, shot.width, shot.height,
            shot.scale, truncated=observed.truncated, total=observed.total)
        prompt = agent.build_typed_prompt(
            PROBE_GOAL, PROBE_MODE, model_w, model_h, session.width,
            session.height, observation_id, target_block, [],
            budgets=None, answer_fields=(), form_fields=())
        probe["observation"] = {"url": shot.url, "seq": observed.seq,
                                "targets": len(observed.targets)}
        proposer = agent.model_proposer(
            adapter, schema=agent.typed_action_schema(PROBE_MODE),
            schema_events=events, require_schema=True)
        adapter.start()
        probe["model_calls"] = 1
        reply = None
        try:
            reply, _meta = proposer(model_bytes, prompt)
            probe["generations"] = 1
        except Exception as exc:  # noqa: BLE001 - record and stop
            probe["error"] = "{}: {}".format(type(exc).__name__, exc)
        probe["schema_events"] = list(events)
        probe["fallbacks"] = sum(1 for item in events if item == "fallback")
        if reply is not None:
            probe["raw_reply"] = json.dumps(reply, sort_keys=True)
            raw_keys = sorted(reply)
            probe["raw_keys"] = raw_keys
            branches = agent.typed_action_schema(PROBE_MODE)["oneOf"]
            matched = []
            for branch in branches:
                props = set(branch["properties"])
                if (set(raw_keys) <= props
                        and reply.get("action")
                        in branch["properties"]["action"]["enum"]):
                    matched.append(branch)
            probe["branch_matches"] = len(matched)
            if len(matched) == 1:
                allowed = set(matched[0]["properties"])
                probe["matched_branch"] = matched[0]["properties"]["action"]["enum"][0]
                probe["cross_talk_fields"] = sorted(set(raw_keys) - allowed)
            proposal = {"kind": reply.get("action")}
            for key in BRANCH_FIELDS:
                if key in reply:
                    proposal[key] = reply[key]
            _parsed, error = tasks.validate_typed_action(
                proposal, mode=PROBE_MODE, observation_id=observation_id,
                targets=observed.targets, authorized_saves=(),
                answer_schema=None)
            probe["validator"] = "ok" if error is None else error
        elif probe["error"] is None:
            probe["error"] = "reply was not one JSON object"
        ok = (probe["generations"] == 1
              and probe["schema_events"] == ["schema"]
              and probe["fallbacks"] == 0
              and probe["branch_matches"] == 1
              and not probe["cross_talk_fields"])
        probe["verdict"] = "PASS" if ok else "BLOCKED"
    except Exception as exc:  # noqa: BLE001 - crash-safe probe
        probe["error"] = "setup: {}: {}".format(type(exc).__name__, exc)
    finally:
        for stopper in (adapter.stop, session.stop, server.stop):
            try:
                stopper()
            except Exception:  # noqa: BLE001
                pass
        check = subprocess.run(["pgrep", "-f", "m018-tools/browser_window"],
                               capture_output=True, text=True)
        probe["orphans"] = len(
            [line for line in check.stdout.split() if line.strip()])

    (out / "probe.json").write_text(
        json.dumps(probe, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(probe, sort_keys=True, indent=2))
    print("PROBE: {} | calls {} | generations {} | events {} | "
          "branch_matches {} | cross_talk {}".format(
              probe["verdict"], probe["model_calls"], probe["generations"],
              probe["schema_events"], probe["branch_matches"],
              probe["cross_talk_fields"]))
    return 0 if probe["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
