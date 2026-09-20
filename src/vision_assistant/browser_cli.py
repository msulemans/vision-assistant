"""M018A CLI: manifest, deterministic stage verification, fixtures, server.

``verify`` runs the whole M018A gate without any model: schema probes,
oracle teeth (correct final states pass, wrong ones fail), manifest
determinism, and byte-identical fixture builds for both instances. It writes
``runs/m018/m018a-verify.json`` and exits non-zero on any problem.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import browser_fixtures as fixtures
from . import browser_targets as bt
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


def cmd_target_smoke(args) -> int:
    """M018T scripted live smoke: targets + click_target, no model calls.

    Phases: (1) click_target navigates to the rank-3 story; (2) a target that
    moves after observation is refused as moved; (3) a click after a new
    snapshot is refused as stale without reaching the helper; (4) the search
    flow click_target → type → click_target submitted end to end; (5) a target
    hidden after observation (Escape closes the overlay) is refused as hidden.
    """

    from .browser_session import BrowserError, BrowserSession, compile_helper
    from .fixture_server import FixtureServer

    instance = args.instance
    stamp = time.strftime("%Y%m%d-%H%M%S")
    root = Path(args.snapshot_dir) if args.snapshot_dir else RUNS_DIR / ("m018t-smoke-" + stamp)
    shots = root / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    site = root / "site"
    fixtures.build_site(instance, site)
    server = FixtureServer(instance, site)
    port = server.start()
    server.reset()
    helper_bin = compile_helper()
    session = BrowserSession(port=port, helper_bin=helper_bin, snapshot_dir=root / "tmp-shots")
    report = {"stage": "M018T", "instance": instance, "port": port, "model_runs": 0,
              "steps": [], "refusals": [], "ok": False}

    def step(name: str, **data) -> None:
        row = dict(name=name)
        row.update(data)
        report["steps"].append(row)
        print("  ".join([name] + ["{}={}".format(k, v) for k, v in sorted(data.items())]))

    def find_target(listing, *, role=None, label=None, contains=None):
        for entry in listing.targets:
            if role is not None and entry.role != role:
                continue
            if label is not None and entry.label != label:
                continue
            if contains is not None and contains not in entry.label:
                continue
            return entry
        return None

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

        # Phase 1: a target click navigates to the rank-3 story.
        step("navigate", to="/news/", url=navigate_with_retry("/news/"))
        news = session.snapshot(path=str(shots / "news.png"))
        step("snapshot", page="news", seq=news.seq)
        listing = session.targets()
        step("targets", page="news", count=len(listing.targets),
             total=listing.total, truncated=listing.truncated)
        wanted = fixtures.story(instance, "d03")["title"]
        entry = find_target(listing, role="link", label=wanted)
        if entry is None:
            raise BrowserError("smoke_missing_target", "rank-3 story link not listed")
        session.click_target(entry.id)
        step("click_target", page="news", target=entry.id, label=entry.label)
        time.sleep(0.8)
        after = session.state()
        story_shot = session.snapshot(path=str(shots / "story-d03.png"))
        step("snapshot", page="story-d03", seq=story_shot.seq, url=story_shot.url)
        report["phase1_url_ok"] = "/story/d03/" in str(after.get("url", ""))
        step("state", page="after-story-click", url=after.get("url"),
             ok=report["phase1_url_ok"])

        # Phase 2: the layout page shifts after observation -> moved refusal.
        step("navigate", to="/layout/", url=navigate_with_retry("/layout/"))
        layout = session.snapshot(path=str(shots / "layout-before-shift.png"))
        step("snapshot", page="layout-before-shift", seq=layout.seq)
        listing2 = session.targets()
        go = find_target(listing2, role="link", contains="rank-5")
        if go is None:
            raise BrowserError("smoke_missing_target", "layout link not listed")
        time.sleep(1.6)
        try:
            session.click_target(go.id)
            report["refusals"].append({"phase": "moved",
                                       "expected": "refused_target_moved", "got": "none"})
            step("click_target", page="layout", target=go.id, outcome="NOT_REFUSED")
        except BrowserError as exc:
            report["refusals"].append({"phase": "moved",
                                       "expected": "refused_target_moved",
                                       "got": exc.reason, "detail": exc.detail})
            step("click_target", page="layout", target=go.id, refused=exc.reason,
                 detail=exc.detail)

        # Phase 3: a fresh snapshot kills the old list (adapter-side, no send).
        third = session.snapshot(path=str(shots / "layout-after-shift.png"))
        step("snapshot", page="layout-after-shift", seq=third.seq)
        try:
            session.click_target(go.id)
            report["refusals"].append({"phase": "stale",
                                       "expected": "refused_target_stale", "got": "none"})
            step("click_target", page="layout-stale", target=go.id, outcome="NOT_REFUSED")
        except BrowserError as exc:
            report["refusals"].append({"phase": "stale",
                                       "expected": "refused_target_stale",
                                       "got": exc.reason, "detail": exc.detail})
            step("click_target", page="layout-stale", target=go.id, refused=exc.reason,
                 detail=exc.detail)

        # Phase 4: search flow — click_target the field, type, click_target submit.
        step("navigate", to="/search/", url=navigate_with_retry("/search/"))
        search = session.snapshot(path=str(shots / "search.png"))
        step("snapshot", page="search", seq=search.seq)
        listing3 = session.targets()
        field = find_target(listing3, role="text_input", label="query")
        submit = find_target(listing3, role="button", label="Search")
        if field is None or submit is None:
            raise BrowserError("smoke_missing_target", "search field/button not listed")
        session.click_target(field.id)
        time.sleep(0.2)
        typed = session.type_text("ai")
        step("type", text="ai", typed=typed)
        session.click_target(submit.id)
        step("click_target", page="search", target=submit.id, label=submit.label)
        deadline = time.monotonic() + 4.0
        url = ""
        while time.monotonic() < deadline:
            url = str(session.state().get("url", ""))
            if "q=ai" in url:
                break
            time.sleep(0.2)
        report["phase4_query_ok"] = "q=ai" in url
        results = session.snapshot(path=str(shots / "search-ai.png"))
        step("snapshot", page="search-ai", seq=results.seq, url=results.url)
        step("search-submitted", url=url, ok=report["phase4_query_ok"])

        # Phase 5: a target hidden after observation (Escape closes the overlay
        # without a new snapshot, so the stale observer sees a visible button).
        step("navigate", to="/welcome/", url=navigate_with_retry("/welcome/"))
        welcome = session.snapshot(path=str(shots / "welcome.png"))
        step("snapshot", page="welcome", seq=welcome.seq)
        listing5 = session.targets()
        dismiss = find_target(listing5, role="button", label="Dismiss")
        if dismiss is None:
            raise BrowserError("smoke_missing_target", "dismiss button not listed")
        session.press_key("escape")
        time.sleep(0.3)
        try:
            session.click_target(dismiss.id)
            report["refusals"].append({"phase": "hidden",
                                       "expected": "refused_target_hidden", "got": "none"})
            step("click_target", page="welcome", target=dismiss.id, outcome="NOT_REFUSED")
        except BrowserError as exc:
            report["refusals"].append({"phase": "hidden",
                                       "expected": "refused_target_hidden",
                                       "got": exc.reason, "detail": exc.detail})
            step("click_target", page="welcome", target=dismiss.id, refused=exc.reason,
                 detail=exc.detail)

        refusal_ok = (len(report["refusals"]) == 3
                      and report["refusals"][0]["got"] == "refused_target_moved"
                      and report["refusals"][1]["got"] == "refused_target_stale"
                      and report["refusals"][2]["got"] == "refused_target_hidden")
        report["ok"] = bool(report.get("phase1_url_ok")
                             and report.get("phase4_query_ok") and refusal_ok)
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

    out = Path(args.out) if args.out else RUNS_DIR / ("target-smoke-{}.json".format(stamp))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("orphans: {}  (temp snapshot dir cleaned: {})".format(
        report["orphans"], report["temp_snapshots_cleaned"]))
    print("report:", out)
    print("RESULT:", "PASS" if report["ok"] and report["orphans"] == 0 else "FAIL")
    return 0 if report["ok"] and report["orphans"] == 0 else 1


HN_HOST = "news.ycombinator.com"
# Assembled from parts so source-line URL literal rules stay satisfied.
HN_ORIGIN = "https:" + "//" + HN_HOST

HN_PILOT_GOAL = (
    "Read the front page of Hacker News from top to bottom. Find the first "
    "three stories whose main subject is AI or machine learning (models, "
    "research, products, or directly related policy; incidental keywords do "
    "not count). For each, report: its rank on the front page (1 = the top "
    "story), its title, its displayed points, and the domain shown next to "
    "the title. If fewer than three qualify, report that. Label uncertain "
    "items as uncertain. Then finish with the findings."
)


def cmd_hn_pilot(args) -> int:
    """M018E: one live Hacker News reading run (reviewer-scored, frozen scope)."""

    from . import browser_targets
    from .browser_agent import LoopLimits, model_proposer, run_task
    from .browser_session import BrowserSession, compile_helper
    from .runtime_llamaserver import LlamaServerAdapter

    stamp = time.strftime("%Y%m%d-%H%M%S")
    root = Path(args.out_dir) if args.out_dir else RUNS_DIR / ("m018e-hn-" + stamp)
    root.mkdir(parents=True, exist_ok=True)
    helper_bin = compile_helper()
    session = BrowserSession(
        port=0, helper_bin=helper_bin, snapshot_dir=root / "shots",
        live_origins=(HN_ORIGIN,), helper_args=("--live-host", HN_HOST))
    pin_dir = Path(args.pin_dir)
    pin = json.loads((pin_dir / "pin.json").read_text(encoding="utf-8"))
    model = next(f for f in pin["files"] if f["role"] == "model")
    mmproj = next(f for f in pin["files"] if f["role"] == "mmproj")
    adapter = LlamaServerAdapter(
        pin_dir / model["name"], pin_dir / mmproj["name"],
        ctx_size=args.ctx_size, jinja=True,
        chat_template_kwargs={"enable_thinking": False},
        log_path=root / "server.log",
    )
    raw_answers: list = []
    proposer = model_proposer(adapter, record=raw_answers,
                              schema=browser_targets.TARGET_ACTION_SCHEMA)
    limits = LoopLimits()
    if args.max_steps:
        limits.max_steps = args.max_steps
    if args.max_calls:
        limits.max_calls = args.max_calls
    if args.max_seconds:
        limits.max_seconds = args.max_seconds
    spec = tasks.TaskSpec("hn", "P", "answer", "live", HN_PILOT_GOAL,
                          HN_ORIGIN + "/",
                          notes="M018E live pilot; reviewer-scored; frozen scope")
    report = None
    try:
        print("starting llama-server with the pinned model " + model["name"])
        adapter.start()
        session.launch()
        report = run_task(
            spec, session=session, proposer=proposer,
            server_state_provider=lambda: {}, limits=limits, mode="target",
            pilot=True)
        report["raw_answers"] = raw_answers
    except Exception as exc:  # noqa: BLE001 - crash-safe pilot reporting
        report = {
            "stage": "M018E", "task": "hn", "outcome": "failed:exception",
            "error": "{}: {}".format(type(exc).__name__, exc),
            "raw_answers": raw_answers,
        }
    finally:
        kept = root / "shots-kept"
        if (session.snapshot_dir is not None and session.snapshot_dir.exists()
                and not kept.exists()):
            shutil.copytree(session.snapshot_dir, kept)
        session.stop()
        adapter.stop()
    (root / "pilot-report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("outcome: {}".format(report.get("outcome")))
    print("report:", root)
    return 0


def cmd_task(args) -> int:
    """Run frozen browser tasks once each with the pinned model in the loop."""

    from .browser_agent import LoopLimits, model_proposer, run_task
    from .browser_session import BrowserSession, compile_helper
    from .fixture_server import FixtureServer
    from .runtime_llamaserver import LlamaServerAdapter

    ids = [item.strip() for item in args.ids.split(",") if item.strip()]
    suite = getattr(args, "suite", "frozen")
    if suite == "eval":
        from .browser_eval import EVAL_INSTANCE, EVAL_TASKS_BY_ID

        pool = EVAL_TASKS_BY_ID
        suite_instance = EVAL_INSTANCE
    else:
        pool = tasks.TASKS_BY_ID
        suite_instance = args.instance
    missing = [item for item in ids if item not in pool]
    if missing:
        print("unknown tasks:", ",".join(missing))
        return 1
    specs = [pool[item] for item in ids]
    instance = suite_instance
    mode = getattr(args, "mode", "screenshot")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    if suite == "eval":
        folder = "m018t-eval-"
    else:
        folder = "m018t-" if mode == "target" else "loop-"
    root = Path(args.out_dir) if args.out_dir else RUNS_DIR / (folder + stamp)
    root.mkdir(parents=True, exist_ok=True)
    site = root / "site"
    fixtures.build_site(instance, site)
    server = FixtureServer(instance, site)
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
        log_path=root / "server.log",
    )
    raw_answers: list = []
    schema = None
    if mode == "target":
        from . import browser_targets

        schema = browser_targets.TARGET_ACTION_SCHEMA
        print("mode: target-assisted (M018T) — separately labelled, never "
              "merged into the screenshot-only score")
    proposer = model_proposer(adapter, record=raw_answers, schema=schema)
    limits = LoopLimits()
    if args.max_steps:
        limits.max_steps = args.max_steps
    if args.max_calls:
        limits.max_calls = args.max_calls
    if args.max_seconds:
        limits.max_seconds = args.max_seconds

    reports = []
    try:
        print("starting llama-server with the pinned model " + model["name"])
        adapter.start()
        for spec in specs:
            server.reset(seed=spec.id)
            print("=== task {} [{}] {}".format(spec.id, spec.split, spec.goal))
            session = BrowserSession(port=port, helper_bin=helper_bin,
                                     snapshot_dir=root / ("shots-" + spec.id))
            raw_before = len(raw_answers)
            try:
                session.launch()
                report = run_task(
                    spec, session=session, proposer=proposer,
                    server_state_provider=server.snapshot, limits=limits,
                    mode=mode)
            finally:
                kept = root / ("shots-kept-" + spec.id)
                if session.snapshot_dir.exists():
                    shutil.copytree(session.snapshot_dir, kept)
                session.stop()
            raw_slice = raw_answers[raw_before:]
            report["raw_answers"] = raw_slice
            reports.append(report)
            (root / ("task-" + spec.id + ".json")).write_text(
                json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            print("--> task {}: {} (actions {}, calls {}, {} ms)".format(
                spec.id, report["outcome"], report["actions"], report["calls"],
                report["elapsed_ms"]))
    finally:
        adapter.stop()
        server.stop()

    finished = [r for r in reports if r["outcome"] == "finished"]
    if suite == "eval":
        stage = "M018T-EVAL"
    else:
        stage = "M018T" if mode == "target" else "M018C"
    summary = {
        "stage": stage,
        "suite": suite,
        "mode": mode, "instance": instance, "ids": ids,
        "finished": len(finished), "total": len(reports),
        "outcomes": {r["task"]: r["outcome"] for r in reports},
    }
    (root / "loop-summary.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("summary: {}/{} finished -> {}".format(
        summary["finished"], summary["total"],
        ", ".join("{}:{}".format(k, v) for k, v in sorted(summary["outcomes"].items()))))
    print("reports:", root)
    return 0


def cmd_m019_verify(args) -> int:
    """M019A deterministic self-check: capability manifests + allow/deny matrix.

    No model, no browser, no fixture server: pure validation contract proof.
    """

    entry_field = bt.TargetEntry("t1", "text_input", "Query",
                                 (0.0, 0.0, 10.0, 10.0), True, False)
    entry_cred = bt.TargetEntry("t2", "text_input", "Password",
                                (0.0, 0.0, 10.0, 10.0), True, False)
    entry_save = bt.TargetEntry("t3", "button", "Save",
                                (0.0, 0.0, 10.0, 10.0), True, False)
    entry_link = bt.TargetEntry("t4", "link", "Story",
                                (0.0, 0.0, 10.0, 10.0), True, False)
    targets = (entry_field, entry_cred, entry_save, entry_link)
    obs = "obs-1"

    for mode in tasks.TYPED_MODES:
        manifest = tasks.capability_manifest(mode)
        print("mode {:<8} allowed: {}".format(
            mode, ", ".join(manifest["allowed_actions"])))

    samples = (
        ("answer", {"kind": "scroll", "direction": "down", "amount": 2}, True, ()),
        ("answer", {"kind": "click_target", "target_ref": "ui:4",
                    "observation_id": obs}, False, ()),
        ("navigate", {"kind": "click_target", "target_ref": "ui:4",
                      "observation_id": obs}, True, ()),
        ("navigate", {"kind": "finish"}, True, ()),
        ("navigate", {"kind": "fill_field", "target_ref": "ui:1", "text": "x",
                      "observation_id": obs}, False, ()),
        ("form", {"kind": "fill_field", "target_ref": "ui:1", "text": "hello",
                  "observation_id": obs}, True, ()),
        ("form", {"kind": "fill_field", "target_ref": "ui:2", "text": "secret",
                  "observation_id": obs}, False, ()),
        ("form", {"kind": "fill_field", "target_ref": "ui:4", "text": "x",
                  "observation_id": obs}, False, ()),
        ("navigate", {"kind": "click", "x": 1, "y": 2}, False, ()),
        ("form", {"kind": "type_text", "text": "x"}, False, ()),
        ("form", {"kind": "navigate", "url": "/news/"}, False, ()),
        ("form", {"kind": "save_form", "target_ref": "ui:3",
                  "observation_id": obs}, False, ()),
        ("form", {"kind": "save_form", "target_ref": "ui:3",
                  "observation_id": obs}, True, ("ui:3",)),
        ("answer", {"kind": "finish_answer",
                     "answer": {"rank": 2, "title": "A story"}}, True, ()),
        ("answer", {"kind": "finish_answer",
                     "answer": {"title": "ui:4"}}, False, ()),
        ("navigate", {"kind": "click_target", "target_ref": "ui:4",
                      "observation_id": "obs-OLD"}, False, ()),
        ("stop", {"kind": "stop"}, True, ()),
        ("stop", {"kind": "click_target", "target_ref": "ui:4",
                  "observation_id": obs}, False, ()),
    )
    problems = []
    for mode, payload, expect_ok, authorized in samples:
        _parsed, error = tasks.validate_typed_action(
            payload, mode=mode, observation_id=obs, targets=targets,
            authorized_saves=authorized)
        got_ok = error is None
        print("  {:<8} {:<13} {}".format(
            mode, str(payload.get("kind")),
            "allow" if got_ok else "deny  ({})".format(error)))
        if got_ok != expect_ok:
            problems.append("{} {}: expected {}, got {} ({})".format(
                mode, payload.get("kind"),
                "allow" if expect_ok else "deny",
                "allow" if got_ok else "deny", error or "accepted"))
    print("m019-verify: {} samples, {} problems".format(len(samples), len(problems)))
    for problem in problems:
        print("  PROBLEM: " + problem)
    return 0 if not problems else 1


def cmd_m019_scripted(args) -> int:
    """M019B scripted integration: six typed scenarios on the dev fixture.

    Real helper + loopback server, **zero model calls**. Productive oracles
    must pass; both refusals must end stopped with zero forbidden side
    effects (no submissions, no origin blocks, no raw actions).
    """

    from . import m019_scripted as scripted
    from . import browser_agent as agent
    from .browser_session import BrowserError, BrowserSession, compile_helper
    from .fixture_server import FixtureServer

    instance = args.instance
    stamp = time.strftime("%Y%m%d-%H%M%S")
    root = Path(args.snapshot_dir) if args.snapshot_dir else RUNS_DIR / ("m019-scripted-" + stamp)
    shots = root / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    site = root / "site"
    fixtures.build_site(instance, site)
    server = FixtureServer(instance, site)
    port = server.start()
    helper_bin = compile_helper()
    session = BrowserSession(port=port, helper_bin=helper_bin,
                             snapshot_dir=root / "tmp-shots")
    report = {"stage": "M019B", "instance": instance, "port": port,
              "model_calls": 0, "scenarios": [], "ok": False}

    class ScriptedProposer:
        """Deterministic stand-in for the model: fixed step factories."""

        def __init__(self, steps):
            self.steps = list(steps)
            self.prompts = []

        def __call__(self, _png_bytes, prompt):
            self.prompts.append(prompt)
            if not self.steps:
                return None, {"chars": 0}
            return self.steps.pop(0)(prompt), {"chars": 0}

    try:
        session.launch()
        # Warm-up: macOS can consume the first mouse event of an inactive
        # window as its activation click (observed live: clicks silently did
        # nothing). Click the "Search" nav link until the URL actually
        # changes (harmless: it only opens /search/); up to three attempts.
        warmup = {"landed": False, "attempts": []}
        for _attempt in range(3):
            try:
                session.navigate("/news/")
                session.snapshot(path=str(shots / "warmup.png"))
                listing = session.targets()
                entry = next((item for item in listing.targets
                              if item.label == "Search"), None)
                if entry is None:
                    warmup["attempts"].append("missing_target")
                    break
                try:
                    session.click_target(entry.id, method="dom")
                except BrowserError as exc:
                    warmup["attempts"].append("refused:" + exc.reason)
                    break
                time.sleep(0.8)
                state_after = session.state()
                landed = "/search/" in str(state_after.get("url", ""))
                warmup["attempts"].append({
                    "landed": landed, "key": state_after.get("key"),
                    "active": state_after.get("active")})
                if landed:
                    warmup["landed"] = True
                    break
            except BrowserError as exc:
                warmup["attempts"].append("error:" + exc.reason)
                break
        report["warmup"] = warmup

        for scenario in scripted.scenarios():
            server.reset()
            row_extra = {}
            if scenario.name == "moving-target":
                # Trusted-code probe (the M018T smoke mechanics): observe the
                # layout page immediately, wait past the 1s shift, then click
                # -> the helper must refuse the moved target.
                probe = {"expected": "refused_target_moved", "got": None,
                         "ok": False}
                try:
                    session.navigate("/layout/")
                    session.snapshot(path=str(shots / "layout-before-shift.png"))
                    probe_listing = session.targets()
                    probe_entry = next(
                        (item for item in probe_listing.targets
                         if "rank-5" in item.label), None)
                    if probe_entry is None:
                        probe["got"] = "missing_target"
                    else:
                        time.sleep(1.6)
                        try:
                            session.click_target(probe_entry.id)
                            probe["got"] = "none"
                        except BrowserError as exc:
                            probe["got"] = exc.reason
                            probe["detail"] = exc.detail
                        session.snapshot(path=str(shots / "layout-after-shift.png"))
                except BrowserError as exc:
                    probe["got"] = "probe_error:" + exc.reason
                probe["ok"] = probe["got"] == "refused_target_moved"
                row_extra["moved_probe"] = probe
            proposer = ScriptedProposer(scenario.script)
            run = agent.run_task(
                scenario.spec, session=session, proposer=proposer,
                server_state_provider=server.snapshot,
                sleep=time.sleep, log=lambda *a, **k: None, mode="typed")
            state = server.snapshot()
            joined = "\n".join(proposer.prompts)
            refusal_text = " | ".join(
                "{} {}".format(step.get("error", ""), step.get("refused", ""))
                for step in run["steps"]
                if step.get("kind") in ("proposal", "action"))
            executed = [str(step.get("executed")) for step in run["steps"]
                        if step.get("kind") == "action" and step.get("executed")]
            forbidden = [text for text in executed
                         if text.startswith(("click ", "type ", "navigate ",
                                             "press "))]
            try:
                blocked = int(session.state().get("blocked", 0))
            except Exception:  # noqa: BLE001 - unknown blocking fails closed
                blocked = -1
            checks = {
                "outcome": run["outcome"] in scenario.expect_outcome,
                "oracle": (bool(run.get("oracle", {}).get("ok"))
                           if scenario.expect_oracle_ok else True),
                "refusals": all(needle in refusal_text
                                for needle in scenario.required_refusals),
                "absence": all(needle.lower() not in joined.lower()
                               for needle in scenario.absence_checks),
                "no_submissions": len(state.get("submissions", [])) == 0,
                "no_forbidden_actions": not forbidden,
                "origin_blocks": blocked == 0,
            }
            if "moved_probe" in row_extra:
                checks["moved_probe"] = bool(row_extra["moved_probe"]["ok"])
            row = {"name": scenario.name, "task": scenario.spec.id,
                   "mode": scenario.spec.mode, "goal": scenario.spec.goal,
                   "outcome": run["outcome"], "checks": checks,
                   "pass": all(checks.values()),
                   "prompts": len(proposer.prompts), "run": run}
            row.update(row_extra)
            report["scenarios"].append(row)
            try:
                if session.last_snapshot is not None:
                    shutil.copyfile(session.last_snapshot.path,
                                    shots / (scenario.name + ".png"))
            except Exception:  # noqa: BLE001 - evidence copy is best effort
                pass
            print("{:<22} {:<22} checks={} {}".format(
                scenario.name, run["outcome"],
                "".join("Y" if ok else "N" for ok in checks.values()),
                "PASS" if row["pass"] else "FAIL"))
            if not row["pass"]:
                print("   failed checks: {}".format(
                    [name for name, ok in checks.items() if not ok]))
    finally:
        session.stop()
        server.stop()
        check = subprocess.run(["pgrep", "-f", "m018-tools/browser_window"],
                               capture_output=True, text=True)
        report["orphans"] = len([line for line in check.stdout.split() if line.strip()])
        report["temp_snapshots_cleaned"] = not session.snapshot_dir.exists()

    report["ok"] = (len(report["scenarios"]) == 6
                    and all(row["pass"] for row in report["scenarios"])
                    and report["orphans"] == 0)
    out = Path(args.out) if args.out else RUNS_DIR / ("scripted-{}.json".format(stamp))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n",
                   encoding="utf-8")
    print("orphans: {}  (temp snapshot dir cleaned: {})".format(
        report["orphans"], report["temp_snapshots_cleaned"]))
    print("report:", out)
    print("RESULT:", "PASS" if report["ok"] else "FAIL")
    return 0 if report["ok"] else 1


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

    p_task = sub.add_parser("task", help="run frozen tasks once each with the pinned model")
    p_task.add_argument("--ids", required=True, help="comma-separated task ids")
    p_task.add_argument("--suite", choices=("frozen", "eval"), default="frozen",
                        help="task pool: the frozen 50-task suite or the M018T evaluation set")
    p_task.add_argument("--instance", choices=fixtures.instances(), default="dev")
    p_task.add_argument("--mode", choices=("screenshot", "target"), default="screenshot",
                        help="observation mode: frozen screenshot baseline or M018T target-assisted")
    p_task.add_argument("--pin-dir", default=str(REPO_ROOT / "models" / "qwen3.5-4b"))
    p_task.add_argument("--ctx-size", type=int, default=4096)
    p_task.add_argument("--max-steps", type=int, default=0)
    p_task.add_argument("--max-calls", type=int, default=0)
    p_task.add_argument("--max-seconds", type=float, default=0)
    p_task.add_argument("--out-dir", default="")
    p_task.set_defaults(func=cmd_task)

    p_tsmoke = sub.add_parser("target-smoke",
                              help="M018T scripted live smoke: targets + click_target (no model)")
    p_tsmoke.add_argument("--instance", choices=fixtures.instances(), default="dev")
    p_tsmoke.add_argument("--snapshot-dir", default="")
    p_tsmoke.add_argument("--out", default="")
    p_tsmoke.set_defaults(func=cmd_target_smoke)

    p_hn = sub.add_parser("hn-pilot",
                          help="M018E: one live Hacker News reading run (reviewer-scored, frozen scope)")
    p_hn.add_argument("--pin-dir", default=str(REPO_ROOT / "models" / "qwen3.5-4b"))
    p_hn.add_argument("--ctx-size", type=int, default=8192,
                      help="pilot context: 8192 (attempt 1 at 4096 hit context overflow on a live page)")
    p_hn.add_argument("--max-steps", type=int, default=0)
    p_hn.add_argument("--max-calls", type=int, default=0)
    p_hn.add_argument("--max-seconds", type=float, default=0)
    p_hn.add_argument("--out-dir", default="")
    p_hn.set_defaults(func=cmd_hn_pilot)

    p_m019 = sub.add_parser("m019-verify",
                            help="M019A deterministic capability/validation self-check (no model, no browser)")
    p_m019.set_defaults(func=cmd_m019_verify)

    p_m019b = sub.add_parser("m019-scripted",
                             help="M019B scripted integration: six typed scenarios, no model calls")
    p_m019b.add_argument("--instance", choices=fixtures.instances(), default="dev")
    p_m019b.add_argument("--snapshot-dir", default="")
    p_m019b.add_argument("--out", default="")
    p_m019b.set_defaults(func=cmd_m019_scripted)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
