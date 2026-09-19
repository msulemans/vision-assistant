"""M015 packaging CLI: build, verify, install, upgrade/rollback, uninstall,
doctor, smoke, and forecast for the local Vision Assistant.

The bundle is self-contained (stdlib-only source + tool sources + manifest +
integrity hashes + installer). Installing creates a versioned prefix with a
`current` symlink and its own venv; upgrades keep old versions; rollback
switches back. Uninstall is a dry run by default and only deletes local
models or captures when the user explicitly passes `--remove-models` /
`--remove-captures`.

Offline contract (frozen): the installer, wrapper, and doctor contain no
network calls; outbound HTTP clients exist only in `runtime_llamaserver.py`
(loopback) and downloads only in `acquire.py` (explicit, one-time). The
`smoke` command replays the read-only profile from the installed copy with
networking switched off.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .acquire import DEFAULT_CANDIDATE
from .manifest import (
    APP_VERSION,
    build_manifest,
    licences_markdown,
    sha256_file,
    size_forecast,
    verify_models,
)
from .profiles import DEFAULT_PROFILE

REPO_ROOT = Path(__file__).resolve().parents[2]

BUNDLE_SRC_GLOB = "*.py"
TOOLS_GLOB = "*.swift"

INSTALL_SCRIPT = """#!/bin/sh
# Vision Assistant installer — offline: creates a venv and lays the bundle
# down. Model acquisition is a separate, explicit, one-time online step.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
PREFIX="${1:-$HOME/.vision-assistant}"
PYTHON="${PYTHON:-python3}"
echo "installing $HERE -> $PREFIX"
mkdir -p "$PREFIX"
if [ ! -x "$PREFIX/venv/bin/python" ]; then
  "$PYTHON" -m venv --without-pip "$PREFIX/venv" 2>/dev/null || "$PYTHON" -m venv "$PREFIX/venv"
fi
PYTHONPATH="$HERE/src" "$PYTHON" -m vision_assistant.package_cli install --bundle "$HERE" --prefix "$PREFIX"
echo "installed. next steps:"
echo "  1) $PREFIX/bin/vision doctor"
echo "  2) provide model files under $PREFIX/models/MODEL_DIR (symlink an existing pin dir, or acquire once while online)"
echo "  3) $PREFIX/bin/vision smoke --with-model"
"""

VISION_WRAPPER = """#!/bin/sh
# Vision Assistant dispatcher (installed copy).
HERE=$(cd "$(dirname "$0")" && pwd)
PREFIX=$(dirname "$HERE")
if [ ! -x "$PREFIX/venv/bin/python" ]; then
  echo "no venv at $PREFIX/venv - run the bundle's install.sh first" >&2
  exit 2
fi
export PYTHONPATH="$PREFIX/current/src"
case "${1:-}" in
  doctor|smoke|forecast|verify|versions|rollback|uninstall|build|install) module=vision_assistant.package_cli ;;
  ask) module=vision_assistant.assistant_cli ;;
  ui) module=vision_assistant.ui_server ;;
  grounding) module=vision_assistant.grounding_cli ;;
  agent) module=vision_assistant.agent_cli ;;
  capture) module=vision_assistant.capture_cli ;;
  *)
    echo "usage: vision <doctor|ask|ui|grounding|agent|capture|smoke|forecast|verify|versions|rollback|uninstall>" >&2
    exit 2
    ;;
esac
shift
exec "$PREFIX/venv/bin/python" -u -m "$module" "$@"
"""

PERMISSION_EDUCATION: tuple[dict, ...] = (
    {
        "capability": "Read a selected window or region",
        "permission": "macOS Screen Recording",
        "why": "window capture uses the system /usr/sbin/screencapture",
        "default": "asked by macOS only when you capture; nothing is captured in the background",
        "revoke": "System Settings > Privacy & Security > Screen Recording",
    },
    {
        "capability": "Ground targets and read element state",
        "permission": "Accessibility",
        "why": "the read-only helper reads roles, names, and frames; it never clicks or types",
        "default": "opt-in only: run `vision grounding --request-permission` yourself; nothing prompts on its own",
        "revoke": "System Settings > Privacy & Security > Accessibility",
    },
    {
        "capability": "Perform supervised actions",
        "permission": "Accessibility",
        "why": "approved presses and value writes, addressed by element identity, in the practice window only",
        "default": "a separate, explicit opt-in; the read-only profile never posts actions",
        "revoke": "same Accessibility toggle; revoking stops actions immediately",
    },
)

NETWORK_CLIENT_TOKENS = ("urllib", "http.client", "requests")
NETWORK_CLIENT_ALLOWLIST = {"runtime_llamaserver.py"}
# URL literals: acquire.py (model downloads) and runtime_llamaserver.py (the
# one dynamic URL, built from `self.host` which defaults to 127.0.0.1 and is
# only ever the locally spawned server). Explicit loopback literals
# (http://127.0.0.1, http://localhost) are allowed everywhere else.
EXTERNAL_URL_ALLOWLIST = {"acquire.py", "runtime_llamaserver.py"}
LOOPBACK_PREFIXES = ("http://127.0.0.1", "http://localhost", "https://127.0.0.1", "https://localhost")
DOWNLOAD_COMMAND_ALLOWLIST = {"acquire.py"}
# The auditor's own source necessarily contains the literal patterns it
# searches for; literal rules skip it (the import rule still applies to it).
LITERAL_RULES_SKIP = {"package_cli.py"}


def _human_bytes(value: int) -> str:
    if value >= 1024**3:
        return f"{value / 1024**3:.2f} GiB"
    if value >= 1024**2:
        return f"{value / 1024**2:.1f} MiB"
    if value >= 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value} B"


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def guess_prefix() -> Path | None:
    """The install prefix when running from an installed copy, else None."""
    parents = Path(__file__).resolve().parents
    if len(parents) >= 5 and parents[3].name == "versions":
        return parents[4]
    return None


def _default_models_dir(prefix: Path | None) -> Path:
    if prefix is not None:
        return prefix / "models" / DEFAULT_CANDIDATE
    return REPO_ROOT / "models" / DEFAULT_CANDIDATE


def _default_pin_dir() -> Path | None:
    candidate = REPO_ROOT / "models" / DEFAULT_CANDIDATE
    return candidate if (candidate / "pin.json").is_file() else None


# ------------------------------------------------------------------ offline audit


def audit_offline(src_dir: Path) -> list[dict]:
    """Frozen source-level offline audit of a product source directory."""
    violations: list[dict] = []
    directory = Path(src_dir)
    if not directory.is_dir():
        return [{"file": str(directory), "rule": "missing", "detail": "source directory not found"}]
    for path in sorted(directory.glob("*.py")):
        name = path.name
        literal_rules = name not in LITERAL_RULES_SKIP
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                for token in NETWORK_CLIENT_TOKENS:
                    if token in stripped and name not in NETWORK_CLIENT_ALLOWLIST:
                        violations.append(
                            {"file": name, "line": number, "rule": "network_client_import", "detail": stripped}
                        )
            if not literal_rules:
                continue
            if "://" in line:
                residue = line
                for prefix in LOOPBACK_PREFIXES:
                    residue = residue.replace(prefix, "")
                if "://" in residue and name not in EXTERNAL_URL_ALLOWLIST:
                    violations.append(
                        {"file": name, "line": number, "rule": "external_url", "detail": stripped}
                    )
            if "0.0.0.0" in line:
                violations.append({"file": name, "line": number, "rule": "wildcard_bind", "detail": stripped})
            if '"curl"' in line or "'curl'" in line:
                if name not in DOWNLOAD_COMMAND_ALLOWLIST:
                    violations.append(
                        {"file": name, "line": number, "rule": "download_command", "detail": stripped}
                    )
    return violations


# ------------------------------------------------------------------ bundle


def _bundle_files(bundle: Path) -> list[Path]:
    return sorted(
        path
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "integrity.json" and "__pycache__" not in path.parts
    )


def write_integrity(bundle: Path) -> dict:
    files = []
    for path in _bundle_files(bundle):
        files.append(
            {
                "path": str(path.relative_to(bundle)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    integrity = {"files": files}
    (bundle / "integrity.json").write_text(
        json.dumps(integrity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return integrity


def readme_install(version: str, manifest: dict) -> str:
    lines = [
        f"# Vision Assistant {version} — install notes",
        "",
        "Local-first, stdlib-only vision assistant. This bundle carries source,",
        "tool sources, the artifact/licence manifest, and an offline installer.",
        "No model weights are included.",
        "",
        "## Prerequisites (a clean Mac)",
        "",
        f"- macOS on Apple silicon; Python ≥ {manifest['python_floor']} (system or pyenv)",
        "- Xcode command line tools (`swiftc`) for the OCR/accessibility helpers",
        "- a llama.cpp runtime (`llama-server`) for model-backed features",
        f"- one-time model acquisition while online (~{size_forecast()['download']['gib']} GiB),",
        "  or point the install at an existing verified pin directory",
        "",
        "## Install (offline)",
        "",
        "```bash",
        "sh install.sh [PREFIX]        # default: ~/.vision-assistant",
        "```",
        "",
        "The installer creates a venv and lays the code down under",
        "`PREFIX/versions/<version>` with a `current` symlink and a `bin/vision`",
        "dispatcher. It never touches the network.",
        "",
        "## Model files (explicit, one-time, online)",
        "",
        "```bash",
        "PYTHONPATH=<repo>/src python3 -m vision_assistant.acquire download \\",
        "  --dir PREFIX/models/qwen3.5-4b",
        "# or link an existing verified pin directory:",
        "ln -s /path/to/models/qwen3.5-4b PREFIX/models/qwen3.5-4b",
        "```",
        "",
        "## First run and verification",
        "",
        "```bash",
        "PREFIX/bin/vision doctor                 # environment + permission education",
        "PREFIX/bin/vision smoke                  # offline audit + model check + grounding gate",
        "PREFIX/bin/vision smoke --with-model     # + one verified read-only ask (try with Wi-Fi off)",
        "```",
        "",
        "## Permissions",
        "",
    ]
    for entry in PERMISSION_EDUCATION:
        lines.append(f"- **{entry['capability']}** — {entry['permission']}: {entry['why']}.")
        lines.append(f"  Default: {entry['default']}. Revoke: {entry['revoke']}.")
    lines += [
        "",
        "## Upgrade, rollback, remove",
        "",
        "```bash",
        "PREFIX/bin/vision install --bundle <newer-bundle> --prefix PREFIX   # upgrade keeps old versions",
        "PREFIX/bin/vision rollback --prefix PREFIX                          # switch back",
        "PREFIX/bin/vision uninstall --prefix PREFIX                         # dry run plan",
        "PREFIX/bin/vision uninstall --prefix PREFIX --apply                 # code only; models/captures kept",
        "PREFIX/bin/vision uninstall --prefix PREFIX --apply --remove-models # explicit model deletion",
        "```",
        "",
        "After install everything runs offline; only `acquire` ever uses the network.",
        "",
        f"Default profile: {DEFAULT_PROFILE} (see manifest.json for measured and planned profiles).",
        "",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ commands


def cmd_forecast(args: argparse.Namespace) -> int:
    forecast = size_forecast(pin_dir=args.pin_dir)
    if args.json:
        print(json.dumps(forecast, indent=2, sort_keys=True))
        return 0
    print(f"download: {_human_bytes(forecast['download']['bytes'])} (one-time, online)")
    for entry in forecast["models"]:
        print(f"  - {entry['name']} ({entry['role']}): {_human_bytes(entry['bytes'])}")
    print(f"on disk:  {_human_bytes(forecast['on_disk']['bytes'])} including venv/bundle estimates")
    print("RAM targets (warm): " + ", ".join(
        f"{name} ≤ {gib:g} GiB" for name, gib in forecast["ram_targets_gib"].items()
    ))
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if out.exists():
        if not args.force:
            print(json.dumps({"status": "failed", "reason": f"{out} exists; use --force"}))
            return 1
        shutil.rmtree(out)
    version = args.version or APP_VERSION
    (out / "src" / "vision_assistant").mkdir(parents=True)
    (out / "tools").mkdir()
    for path in sorted((REPO_ROOT / "src" / "vision_assistant").glob(BUNDLE_SRC_GLOB)):
        shutil.copy2(path, out / "src" / "vision_assistant" / path.name)
    for path in sorted((REPO_ROOT / "tools").glob(TOOLS_GLOB)):
        shutil.copy2(path, out / "tools" / path.name)
    (out / "VERSION").write_text(version + "\n", encoding="utf-8")
    manifest = build_manifest(pin_dir=args.pin_dir or _default_pin_dir())
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "LICENCES.md").write_text(licences_markdown(manifest), encoding="utf-8")
    (out / "README-INSTALL.md").write_text(readme_install(version, manifest), encoding="utf-8")
    install = out / "install.sh"
    install.write_text(INSTALL_SCRIPT, encoding="utf-8")
    os.chmod(install, 0o755)
    integrity = write_integrity(out)
    total = sum(entry["bytes"] for entry in integrity["files"])
    print(
        json.dumps(
            {
                "status": "ok",
                "bundle": str(out),
                "version": version,
                "files": len(integrity["files"]),
                "bytes": total,
                "default_profile": DEFAULT_PROFILE,
            },
            sort_keys=True,
        )
    )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    bundle = Path(args.bundle)
    integrity_path = bundle / "integrity.json"
    if not integrity_path.is_file():
        print(json.dumps({"status": "failed", "reason": f"no integrity.json in {bundle}"}))
        return 1
    integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    mismatches = []
    for entry in integrity["files"]:
        path = bundle / entry["path"]
        if not path.is_file():
            mismatches.append({"path": entry["path"], "problem": "missing"})
            continue
        if path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            mismatches.append({"path": entry["path"], "problem": "content"})
    violations = audit_offline(bundle / "src" / "vision_assistant")
    ok = not mismatches and not violations
    report = {
        "status": "ok" if ok else "failed",
        "bundle": str(bundle),
        "version": (bundle / "VERSION").read_text(encoding="utf-8").strip()
        if (bundle / "VERSION").is_file()
        else None,
        "files_checked": len(integrity["files"]),
        "mismatches": mismatches,
        "offline_audit": {"ok": not violations, "violations": violations},
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if ok else 1


def _load_history(prefix: Path) -> dict:
    path = prefix / "install.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"entries": []}


def _append_history(prefix: Path, **entry: object) -> dict:
    history = _load_history(prefix)
    history["entries"].append({**entry, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    (prefix / "install.json").write_text(
        json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return history


def _current_version(prefix: Path) -> str | None:
    link = prefix / "current"
    if link.is_symlink():
        target = os.readlink(link)
        return Path(target).name
    return None


def _set_current(prefix: Path, version: str) -> None:
    link = prefix / "current"
    tmp = prefix / f"current.tmp-{os.getpid()}"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(f"versions/{version}", tmp)
    os.replace(tmp, link)


def cmd_install(args: argparse.Namespace) -> int:
    bundle = Path(args.bundle)
    version_file = bundle / "VERSION"
    if not version_file.is_file():
        print(json.dumps({"status": "failed", "reason": f"no VERSION in {bundle}"}))
        return 1
    version = version_file.read_text(encoding="utf-8").strip()
    prefix = Path(args.prefix)
    target = prefix / "versions" / version
    previous = _current_version(prefix)
    if target.exists():
        if not args.force:
            print(
                json.dumps(
                    {"status": "failed", "reason": f"version {version} already installed; use --force"}
                )
            )
            return 1
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(bundle, target, ignore=shutil.ignore_patterns("__pycache__"))
    _set_current(prefix, version)
    bin_dir = prefix / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    wrapper = bin_dir / "vision"
    wrapper.write_text(VISION_WRAPPER, encoding="utf-8")
    os.chmod(wrapper, 0o755)
    action = "install" if previous is None else ("upgrade" if previous != version else "reinstall")
    _append_history(prefix, version=version, action=action, previous=previous)
    print(
        json.dumps(
            {
                "status": "ok",
                "prefix": str(prefix),
                "version": version,
                "previous": previous,
                "action": action,
                "wrapper": str(wrapper),
            },
            sort_keys=True,
        )
    )
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    prefix = Path(args.prefix)
    current = _current_version(prefix)
    if current is None:
        print(json.dumps({"status": "failed", "reason": f"no current version at {prefix}"}))
        return 1
    candidates = [
        entry["version"]
        for entry in reversed(_load_history(prefix)["entries"])
        if entry["version"] != current and (prefix / "versions" / entry["version"]).is_dir()
    ]
    if not candidates:
        print(json.dumps({"status": "failed", "reason": "no previous version to roll back to"}))
        return 1
    target = candidates[0]
    _set_current(prefix, target)
    _append_history(prefix, version=target, action="rollback", previous=current)
    print(json.dumps({"status": "ok", "prefix": str(prefix), "version": target, "previous": current}, sort_keys=True))
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    prefix = Path(args.prefix)
    code_paths = [prefix / "versions", prefix / "current", prefix / "bin", prefix / "venv"]
    models = prefix / "models"
    captures = prefix / "captures"
    plan = {
        "prefix": str(prefix),
        "remove": [
            {"path": str(path), "bytes": _dir_size(path) if path.is_dir() else 0}
            for path in code_paths
            if path.exists() or path.is_symlink()
        ],
        "keep": [],
        "remove_models": bool(args.remove_models),
        "remove_captures": bool(args.remove_captures),
    }
    for path, remove in ((models, args.remove_models), (captures, args.remove_captures)):
        if path.exists():
            entry = {"path": str(path), "bytes": _dir_size(path)}
            (plan["remove"] if remove else plan["keep"]).append(entry)
    if not args.apply:
        print(json.dumps({"status": "dry_run", **plan}, indent=2, sort_keys=True))
        print("nothing was deleted; re-run with --apply (models and captures stay unless asked)")
        return 0
    for path in code_paths:
        if path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
    removed = [entry["path"] for entry in plan["remove"]]
    for path, remove in ((models, args.remove_models), (captures, args.remove_captures)):
        if remove and path.exists():
            shutil.rmtree(path)
    _append_history(
        prefix, version=_current_version(prefix) or "none", action="uninstall", removed=removed
    )
    print(json.dumps({"status": "ok", "removed": removed, "kept": [e["path"] for e in plan["keep"]]}, sort_keys=True))
    return 0


def cmd_versions(args: argparse.Namespace) -> int:
    prefix = Path(args.prefix)
    versions_dir = prefix / "versions"
    installed = sorted(path.name for path in versions_dir.iterdir() if path.is_dir()) if versions_dir.is_dir() else []
    print(
        json.dumps(
            {
                "prefix": str(prefix),
                "current": _current_version(prefix),
                "installed": installed,
                "history": _load_history(prefix)["entries"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


# ------------------------------------------------------------------ doctor


def _accessibility_probe() -> dict:
    from .ax_vision import AxUnavailable, AxVisionAdapter

    try:
        state = AxVisionAdapter().check()
        return {"trusted": bool(state.get("trusted"))}
    except AxUnavailable as exc:  # noqa: PERF203 - typed report
        return {"trusted": None, "error": exc.reason}


def _real_probes() -> dict:
    runtime = None
    llama = shutil.which("llama-server")
    if llama:
        version = None
        try:
            done = subprocess.run([llama, "--version"], capture_output=True, text=True, timeout=15)
            text = (done.stdout or done.stderr).strip()
            if text:
                version = text.splitlines()[0][:100]
        except Exception:  # noqa: BLE001 - best effort probe
            version = None
        runtime = {"path": llama, "version": version}
    screencapture = shutil.which("screencapture")
    if screencapture is None and Path("/usr/sbin/screencapture").exists():
        screencapture = "/usr/sbin/screencapture"
    return {
        "python_version": sys.version.split()[0],
        "python_ok": sys.version_info >= (3, 9),
        "swiftc": shutil.which("swiftc"),
        "llama_server": runtime,
        "screencapture": screencapture,
        "accessibility": _accessibility_probe(),
    }


def doctor_report(
    *,
    prefix: Path | None = None,
    models_dir: Path | None = None,
    probes: dict | None = None,
) -> dict:
    probe_values = dict(probes) if probes is not None else _real_probes()
    directory = Path(models_dir) if models_dir is not None else _default_models_dir(prefix)
    if (directory / "pin.json").is_file():
        models = verify_models(directory, mode="size")
    else:
        models = {
            "ok": False,
            "reason": "not_found",
            "directory": str(directory),
            "files": [],
            "hint": "link or acquire the pinned model directory, then re-run doctor",
        }
    installed = None
    if prefix is not None and (prefix / "install.json").is_file():
        history = _load_history(prefix)["entries"]
        installed = {
            "prefix": str(prefix),
            "current": _current_version(prefix),
            "history_entries": len(history),
        }
    return {
        "probes": probe_values,
        "models": models,
        "install": installed,
        "permissions": [dict(entry) for entry in PERMISSION_EDUCATION],
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    prefix = Path(args.prefix) if args.prefix else guess_prefix()
    models_dir = Path(args.models_dir) if args.models_dir else None
    report = doctor_report(prefix=prefix, models_dir=models_dir)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    probes = report["probes"]
    print("environment")
    print(f"  python:        {probes['python_version']} (ok={probes['python_ok']})")
    print(f"  swiftc:        {probes['swiftc'] or 'missing (needed for helpers)'}")
    llama = probes["llama_server"]
    print(f"  llama-server:  {(llama['path'] + ' ' + (llama['version'] or '')) if llama else 'missing (needed for model features)'}")
    print(f"  screencapture: {probes['screencapture'] or 'missing'}")
    access = probes["accessibility"]
    trust = access.get("trusted")
    print(f"  accessibility: {'granted' if trust else ('not granted' if trust is False else 'unavailable')}"
          + (f" ({access.get('error')})" if access.get("error") else ""))
    models = report["models"]
    print("models")
    print(f"  directory: {models['directory']} -> {'ok' if models.get('ok') else models.get('reason')}")
    for entry in models.get("files", []):
        print(f"    - {entry['name']}: present={entry['present']} size_ok={entry['size_ok']}")
    if models.get("hint"):
        print(f"  hint: {models['hint']}")
    if report["install"]:
        print("install")
        print(f"  prefix {report['install']['prefix']} current={report['install']['current']} "
              f"history={report['install']['history_entries']} entries")
    print("permissions (nothing prompts on its own)")
    for entry in report["permissions"]:
        print(f"  - {entry['capability']}: {entry['permission']}")
        print(f"      why: {entry['why']}")
        print(f"      default: {entry['default']}")
        print(f"      revoke: {entry['revoke']}")
    return 0


# ------------------------------------------------------------------ smoke


def _model_smoke(models_dir: Path, out_dir: Path) -> dict:
    from .assistant import answer_frame, preview_image
    from .grounding_fixture import all_variants
    from .runtime_llamaserver import LlamaServerAdapter

    pin = json.loads((models_dir / "pin.json").read_text(encoding="utf-8"))
    model = next(item for item in pin["files"] if item["role"] == "model")
    mmproj = next(item for item in pin["files"] if item["role"] == "mmproj")
    fixture_dir = out_dir / "fixture"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = fixture_dir / "smoke-fixture.png"
    fixture_path.write_bytes(all_variants()[0].image_png)
    trace_dir = out_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_id = f"smoke-{time.strftime('%Y%m%d-%H%M%S')}"
    preview, frame, store, _ingestor = preview_image(
        fixture_path, artifacts_root=out_dir / "artifacts", trace_id=trace_id
    )
    adapter = LlamaServerAdapter(
        models_dir / model["name"],
        models_dir / mmproj["name"],
        ctx_size=4096,
        jinja=True,
        chat_template_kwargs={"enable_thinking": False},
        log_path=out_dir / "smoke-server.log",
    )
    started = time.monotonic()
    try:
        adapter.start()
        result = answer_frame(
            frame,
            "List the interactive controls visible in this window.",
            adapter=adapter,
            trace_dir=trace_dir,
            store=store,
        )
    finally:
        adapter.stop()
    answer = result.get("answer") or {}
    labels = len(answer.get("visible", [])) + len(answer.get("inferred", [])) + len(answer.get("unknown", []))
    return {
        "ok": bool(result.get("released")) and labels >= 1,
        "image": {"width": preview.width, "height": preview.height},
        "answer_labels": labels,
        "released": bool(result.get("released")),
        "timing_ms": result.get("timing_ms"),
        "total_ms": round((time.monotonic() - started) * 1000.0, 1),
        "trace": result.get("trace_path"),
    }


def cmd_smoke(args: argparse.Namespace) -> int:
    prefix = Path(args.prefix) if args.prefix else guess_prefix()
    root = (prefix / "current") if prefix is not None else REPO_ROOT
    src_dir = root / "src" / "vision_assistant"
    if not src_dir.is_dir():
        print(json.dumps({"status": "failed", "reason": f"no product source at {src_dir}"}))
        return 1
    out_dir = Path(args.out_dir) if args.out_dir else (
        (prefix / "runs" / "m015") if prefix is not None else (REPO_ROOT / "runs" / "m015")
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    violations = audit_offline(src_dir)
    models_dir = Path(args.models_dir) if args.models_dir else _default_models_dir(prefix)
    if (models_dir / "pin.json").is_file():
        models = verify_models(models_dir, mode="hash" if args.full_hash else "size")
    else:
        models = {"ok": False, "reason": "not_found", "directory": str(models_dir), "files": []}

    from .grounding_eval import run_frozen_gate

    gate = run_frozen_gate(write=False)["summary"]

    model_step = None
    if args.with_model and models.get("ok"):
        model_step = _model_smoke(models_dir, out_dir)

    checks = {
        "offline_audit": not violations,
        "models": bool(models.get("ok")),
        "grounding_gate": bool(gate["gate_pass"]),
    }
    if args.with_model:
        checks["model_smoke"] = bool(model_step and model_step["ok"])
    passed = all(checks.values())
    report = {
        "run_id": f"m015-smoke-{time.strftime('%Y%m%d-%H%M%S')}",
        "root": str(root),
        "checks": checks,
        "passed": passed,
        "offline_violations": violations,
        "models": models,
        "grounding": gate,
        "model_smoke": model_step,
    }
    path = out_dir / f"{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"offline audit: {'ok' if checks['offline_audit'] else 'VIOLATIONS'}"
          + (f" ({len(violations)})" if violations else ""))
    print(f"models: {'ok' if checks['models'] else models.get('reason')} ({models.get('directory')})")
    print(f"grounding gate: {gate['passed']}/{gate['checks']} checks, gate_pass={gate['gate_pass']}")
    if model_step is not None:
        print(f"model smoke: ok={model_step['ok']} labels={model_step['answer_labels']} "
              f"released={model_step['released']} total={model_step['total_ms']} ms")
    print(f"result: {path}")
    return 0 if passed else 1


# ------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vision_assistant.package_cli",
        description="M015 packaging: build, verify, install, doctor, smoke, forecast",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    forecast = sub.add_parser("forecast", help="disk and memory forecast")
    forecast.add_argument("--pin-dir", type=Path, default=None)
    forecast.add_argument("--json", action="store_true")
    forecast.set_defaults(func=cmd_forecast)

    build = sub.add_parser("build", help="build a self-contained bundle")
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--version", default=None)
    build.add_argument("--pin-dir", type=Path, default=None)
    build.add_argument("--force", action="store_true")
    build.set_defaults(func=cmd_build)

    verify = sub.add_parser("verify", help="verify bundle integrity + offline audit")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.set_defaults(func=cmd_verify)

    install = sub.add_parser("install", help="install/upgrade a bundle into a prefix")
    install.add_argument("--bundle", type=Path, required=True)
    install.add_argument("--prefix", type=Path, required=True)
    install.add_argument("--force", action="store_true")
    install.set_defaults(func=cmd_install)

    rollback = sub.add_parser("rollback", help="switch back to the previous version")
    rollback.add_argument("--prefix", type=Path, required=True)
    rollback.set_defaults(func=cmd_rollback)

    uninstall = sub.add_parser("uninstall", help="dry-run plan or --apply removal")
    uninstall.add_argument("--prefix", type=Path, required=True)
    uninstall.add_argument("--apply", action="store_true")
    uninstall.add_argument("--remove-models", action="store_true")
    uninstall.add_argument("--remove-captures", action="store_true")
    uninstall.set_defaults(func=cmd_uninstall)

    versions = sub.add_parser("versions", help="list installed versions and history")
    versions.add_argument("--prefix", type=Path, required=True)
    versions.set_defaults(func=cmd_versions)

    doctor = sub.add_parser("doctor", help="environment report + first-run permission education")
    doctor.add_argument("--prefix", type=Path, default=None)
    doctor.add_argument("--models-dir", type=Path, default=None)
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    smoke = sub.add_parser("smoke", help="offline audit + model check + grounding gate (+ model ask)")
    smoke.add_argument("--prefix", type=Path, default=None)
    smoke.add_argument("--models-dir", type=Path, default=None)
    smoke.add_argument("--out-dir", type=Path, default=None)
    smoke.add_argument("--with-model", action="store_true")
    smoke.add_argument("--full-hash", action="store_true")
    smoke.set_defaults(func=cmd_smoke)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
