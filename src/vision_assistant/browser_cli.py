"""M018A CLI: manifest, deterministic stage verification, fixtures, server.

``verify`` runs the whole M018A gate without any model: schema probes,
oracle teeth (correct final states pass, wrong ones fail), manifest
determinism, and byte-identical fixture builds for both instances. It writes
``runs/m018/m018a-verify.json`` and exits non-zero on any problem.
"""

from __future__ import annotations

import argparse
import json
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
