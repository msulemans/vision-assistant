"""M018A CLI: manifest, deterministic stage verification, fixtures, server.

``verify`` runs the whole M018A gate without any model: schema probes,
oracle teeth (correct final states pass, wrong ones fail), manifest
determinism, and byte-identical fixture builds for both instances. It writes
``runs/m018/m018a-verify.json`` and exits non-zero on any problem.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import browser_fixtures as fixtures
from . import browser_tasks as tasks

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs" / "m018"


def cmd_manifest(args) -> int:
    text = tasks.manifest_json()
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    payload = json.loads(text)
    print("M018A manifest {} — {} tasks ({} dev / {} held-out); smoke: {}".format(
        payload["manifest_version"], len(payload["tasks"]),
        sum(1 for t in payload["tasks"] if t["split"] == "D"),
        sum(1 for t in payload["tasks"] if t["split"] == "H"),
        ", ".join(t["id"] for t in payload["tasks"] if t["smoke"]),
    ))
    for instance, info in sorted(payload["instances"].items()):
        print("floor {:<8} content {} {}".format(
            instance, info["content_version"], info["content_hash"][:16]))
    if args.out:
        print("written:", args.out)
    return 0


def cmd_site(args) -> int:
    result = fixtures.build_site(args.instance, args.dest)
    print("fixture site {} -> {} files, tree {}".format(
        args.instance, result["files"], result["tree_sha256"][:16]))
    print("dest:", args.dest)
    return 0


def cmd_verify(args) -> int:
    checks = tasks.run_manifest_checks()
    builds = {}
    with tempfile.TemporaryDirectory() as tmp:
        for instance in fixtures.instances():
            first = fixtures.build_site(instance, Path(tmp) / instance / "a")
            second = fixtures.build_site(instance, Path(tmp) / instance / "b")
            builds[instance] = {
                "files": first["files"],
                "tree_sha256": first["tree_sha256"],
                "byte_identical": first == second,
            }
    ok = checks["ok"] and all(item["byte_identical"] for item in builds.values())
    report = {
        "stage": "M018A",
        "ok": ok,
        "model_runs": 0,
        "manifest_checks": checks,
        "fixture_builds": builds,
    }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out = RUNS_DIR / "m018a-verify.json"
    out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("M018A verify — tasks: {} ({} dev / {} held-out), smoke {}".format(
        checks["tasks"], checks["split_dev"], checks["split_heldout"],
        ",".join(checks["smoke_tasks"])))
    print("schema adversarial: {}/{} rejected".format(
        checks["adversarial_rejected"], checks["adversarial_total"]))
    print("oracles: {}/{} correct states pass, {}/{} wrong states rejected".format(
        checks["positive_pass"], checks["positive_total"],
        checks["mutations_rejected"], checks["mutations_total"]))
    print("manifest sha256: {}".format(checks["manifest_sha256"][:16]))
    for instance, item in sorted(builds.items()):
        print("fixture {}: {} files, byte-identical rebuild: {}".format(
            instance, item["files"], item["byte_identical"]))
    for problem in checks["problems"]:
        print("PROBLEM:", problem)
    print("report:", out)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def cmd_serve(args) -> int:
    from .fixture_server import FixtureServer

    site_dir = Path(args.site) if args.site else RUNS_DIR / ("site-" + args.instance)
    if args.rebuild or not site_dir.exists():
        result = fixtures.build_site(args.instance, site_dir)
        print("fixture site {} built: {} files, tree {}".format(
            args.instance, result["files"], result["tree_sha256"][:16]))
    server = FixtureServer(args.instance, site_dir)
    port = server.start(port=args.port)
    print("fixture {} serving {} (state at {}/__state, reset {}/__reset)".format(
        args.instance, server.base_url, server.base_url, server.base_url))
    print("Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
        print("\nfixture server stopped.")
    return 0


def cmd_smoke(args) -> int:
    """Live scripted smoke: fixture server + real helper, typed steps, no model."""

    from .browser_session import BrowserError, BrowserSession, compile_helper
    from .fixture_server import FixtureServer

    instance = args.instance
    stamp = time.strftime("%Y%m%d-%H%M%S")
    root = Path(args.snapshot_dir) if args.snapshot_dir else RUNS_DIR / ("smoke-" + stamp)
    shots = root / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    site = root / "site"
    fixtures.build_site(instance, site)
    server = FixtureServer(instance, site)
    port = server.start()
    server.reset()
    helper_bin = compile_helper()
    session = BrowserSession(port=port, helper_bin=helper_bin, snapshot_dir=root / "tmp-shots")
    report = {"stage": "M018B", "instance": instance, "port": port, "model_runs": 0,
              "steps": [], "ok": False}

    def step(name: str, **data) -> None:
        row = dict(name=name)
        row.update(data)
        report["steps"].append(row)
        print("  ".join([name] + ["{}={}".format(k, v) for k, v in sorted(data.items())]))

    SETTLE_S = 0.8

    def navigate_with_retry(target: str) -> str:
        try:
            return session.navigate(target)
        except BrowserError as exc:
            if exc.reason == "navigation_failed" and "-999" in exc.detail:
                time.sleep(0.4)
                return session.navigate(target)
            raise

    try:
        session.launch()
        step("launch", ready=True, helper=str(helper_bin))
        step("navigate", to="/news/", url=navigate_with_retry("/news/"))
        news = session.snapshot(path=str(shots / "news.png"))
        step("snapshot", page="news", seq=news.seq, width=news.width, height=news.height,
             scale=news.scale, path=str(news.path))
        state = session.state()
        step("state", page="news", url=state.get("url"), blocked=state.get("blocked"))
        if args.story_click:
            x, y = args.story_click
            session.click(x, y)
            step("click-story", x=x, y=y)
            time.sleep(SETTLE_S)
            after = session.state()
            step("state", page="after-story-click", url=after.get("url"), settle_s=SETTLE_S)
            story = session.snapshot(path=str(shots / "story-after-click.png"))
            step("snapshot", page="story-after-click", seq=story.seq, url=story.url)
        step("navigate", to="/search/", url=navigate_with_retry("/search/"))
        search = session.snapshot(path=str(shots / "search.png"))
        step("snapshot", page="search", seq=search.seq, width=search.width,
             height=search.height, scale=search.scale, path=str(search.path))
        if args.type_click:
            x, y = args.type_click
            session.click(x, y)
            step("click-input", x=x, y=y)
            time.sleep(0.4)
            typed = session.type_text("ai")
            focused = (session.state().get("focused") or {})
            step("type", text="ai", typed=typed, value_length=focused.get("valueLength"))
            report["typed_ok"] = focused.get("valueLength") == 2
        report["ok"] = True
    except BrowserError as exc:
        report["error"] = {"reason": exc.reason, "detail": exc.detail}
        step("error", reason=exc.reason, detail=exc.detail)
    finally:
        session.stop()
        server.stop()
        check = subprocess.run(["pgrep", "-f", "m018-tools/browser_window"],
                               capture_output=True, text=True)
        report["orphans"] = len([line for line in check.stdout.split() if line.strip()])
        report["temp_snapshots_cleaned"] = not session.snapshot_dir.exists()

    out = Path(args.out) if args.out else RUNS_DIR / ("browser-smoke-{}.json".format(stamp))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("orphans: {}  (temp snapshot dir cleaned: {})".format(
        report["orphans"], report["temp_snapshots_cleaned"]))
    print("report:", out)
    print("RESULT:", "PASS" if report["ok"] and report["orphans"] == 0 else "FAIL")
    return 0 if report["ok"] and report["orphans"] == 0 else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="browser_cli", description="M018A fixture/browser-task stage tooling")
    sub = parser.add_subparsers(dest="command", required=True)

    p_manifest = sub.add_parser("manifest", help="print/write the 50-task manifest")
    p_manifest.add_argument("--out", default="")
    p_manifest.set_defaults(func=cmd_manifest)

    p_verify = sub.add_parser("verify", help="deterministic M018A gate: schema, oracles, builds")
    p_verify.set_defaults(func=cmd_verify)

    p_site = sub.add_parser("site", help="generate a fixture site")
    p_site.add_argument("--instance", choices=fixtures.instances(), required=True)
    p_site.add_argument("--dest", required=True)
    p_site.set_defaults(func=cmd_site)

    p_serve = sub.add_parser("serve", help="serve a fixture site on loopback")
    p_serve.add_argument("--instance", choices=fixtures.instances(), required=True)
    p_serve.add_argument("--site", default="")
    p_serve.add_argument("--port", type=int, default=0)
    p_serve.add_argument("--rebuild", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    p_smoke = sub.add_parser("smoke", help="live scripted smoke of the browser helper")
    p_smoke.add_argument("--instance", choices=fixtures.instances(), default="dev")
    p_smoke.add_argument("--story-click", type=int, nargs=2, metavar=("X", "Y"),
                         help="screenshot-pixel click on the rank-3 story link")
    p_smoke.add_argument("--type-click", type=int, nargs=2, metavar=("X", "Y"),
                         help="screenshot-pixel click on the search query input")
    p_smoke.add_argument("--snapshot-dir", default="")
    p_smoke.add_argument("--out", default="")
    p_smoke.set_defaults(func=cmd_smoke)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
