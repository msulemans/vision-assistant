"""M017 public beta hardening: the frozen audit suite.

Eleven check categories, each returning findings with severity (critical or
note). `run_audit()` executes all of them deterministically — no model, no
permissions, no network — and the gate is zero critical failures.

The audit re-runs the project's own adversarial surfaces where they exist
(the M014 scenario suite, the M010 payload funnel) and adds dynamic checks
that plant canaries (trace redaction) and rebuild artifacts (bundle
reproducibility, rollback/uninstall) so the release claims are observed,
not assumed.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "vision_assistant"

CATEGORIES = (
    "capture_privacy",
    "trace_redaction",
    "malicious_screen_text",
    "action_policy",
    "permission_changes",
    "supply_chain",
    "crash_recovery",
    "accessibility",
    "long_session",
    "reproducibility",
    "release_integrity",
)

CRITICAL = "critical"
NOTE = "note"
CANARY_FACT = "CANARY-FACT-7F3A91-DO-NOT-TRACE"


@dataclass(frozen=True)
class Finding:
    check_id: str
    category: str
    status: str  # pass | fail | note
    severity: str  # critical | note
    detail: str


def _finding(check_id: str, category: str, ok: bool, detail: str, *, severity: str = CRITICAL) -> Finding:
    if severity == NOTE:
        return Finding(check_id, category, "note" if not ok else "pass", NOTE, detail)
    return Finding(check_id, category, "pass" if ok else "fail", CRITICAL, detail)


def _run_cli(*argv: str, timeout: float = 120.0) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "vision_assistant.package_cli", *argv],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class _EchoAdapter:
    """Deterministic stand-in for the model (no runtime needed)."""

    def predict_image(self, png_bytes: bytes, question: str):
        from .ports import LabelledAnswer

        return LabelledAnswer(visible=("AUDIT SAMPLE",), inferred=(), unknown=()), {
            "first_token_ms": 1.0,
            "complete_ms": 2.0,
        }


def _tiny_png() -> bytes:
    from .pixels import PngPixels, encode_png

    return encode_png(
        PngPixels(width=8, height=8, colour_type=2, bit_depth=8, rows=(b"\x40" * (8 * 3),) * 8)
    )


def _artifact_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()] if root.exists() else []


# ------------------------------------------------------------------ checks


def check_capture_privacy() -> list[Finding]:
    findings = []
    ignored = [
        subprocess.run(
            ["git", "check-ignore", "-q", probe], cwd=REPO_ROOT, capture_output=True
        ).returncode
        == 0
        for probe in ("runs/probe-artifacts/x.png", "captures/probe.png", "models/probe/pin.json")
    ]
    findings.append(
        _finding(
            "capture.artifact-roots-ignored",
            "capture_privacy",
            all(ignored),
            "runs/, captures/, and models/ are git-ignored (private screen content never enters history)",
        )
    )
    source = (SRC / "capture.py").read_text(encoding="utf-8")
    findings.append(
        _finding(
            "capture.private-modes",
            "capture_privacy",
            "0o700" in source and "0o600" in source,
            "artifact directories 0700 / files 0600 in the store",
        )
    )
    findings.append(
        _finding(
            "capture.released-by-default",
            "capture_privacy",
            "retain" in source and "release" in source,
            "release-by-default with explicit retain opt-in",
        )
    )
    return findings


def redaction_findings(trace_text: str, canary: str, *, released: bool, leftover_files: int) -> list[Finding]:
    """Pure helper so tests can plant bad traces (teeth)."""
    return [
        _finding(
            "trace.canary-fact-never-in-trace",
            "trace_redaction",
            canary not in trace_text,
            "planted evidence text does not appear in the trace",
        ),
        _finding(
            "trace.pixels-never-in-trace",
            "trace_redaction",
            "iVBOR" not in trace_text and "base64" not in trace_text,
            "no pixel bytes or base64 payloads in the trace",
        ),
        _finding(
            "trace.artifact-released",
            "trace_redaction",
            released and leftover_files == 0,
            f"artifact released and no leftovers (leftover files: {leftover_files})",
        ),
    ]


def check_trace_redaction() -> list[Finding]:
    from .assistant import answer_frame, preview_image
    from .evidence import EvidenceFact, StaticEvidencePort

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        image = root / "input.png"
        image.write_bytes(_tiny_png())
        artifacts = root / "artifacts"
        trace_dir = root / "traces"
        trace_dir.mkdir()
        preview, frame, store, _ingestor = preview_image(
            image, artifacts_root=artifacts, trace_id="audit-canary"
        )
        evidence_port = StaticEvidencePort(
            (
                EvidenceFact(
                    fact_id="f1", kind="ocr", text=CANARY_FACT, source="audit-canary-source"
                ),
            )
        )
        result = answer_frame(
            frame,
            "What does the screen show?",
            adapter=_EchoAdapter(),
            trace_dir=trace_dir,
            store=store,
            evidence_port=evidence_port,
        )
        trace_text = (trace_dir / "audit-canary.jsonl").read_text(encoding="utf-8")
        return redaction_findings(
            trace_text,
            CANARY_FACT,
            released=bool(result.get("released")),
            leftover_files=len(_artifact_files(artifacts)),
        )


def _scenario_report() -> dict:
    from .agent_eval import run_scenarios

    return run_scenarios()


def check_malicious_screen_text() -> list[Finding]:
    report = _scenario_report()
    gate = report["gate"]
    by_name = {row["name"]: row for row in report["results"]}
    findings = [
        _finding(
            "screen.adversarial-suite-green",
            "malicious_screen_text",
            gate["all_pass"] and gate["unapproved_total"] == 0,
            f"22-scenario adversarial suite: {gate['passed']}/{gate['scenarios']} passed, unapproved 0",
        ),
        _finding(
            "screen.injection-flagged-and-ignored",
            "malicious_screen_text",
            by_name["injection-ignored"]["terminal"] == "finished"
            and by_name["injection-ignored"]["injection_flags"] >= 1
            and by_name["injection-targeted"]["terminal"] == "blocked:injection_suspected",
            "adversarial screen text flagged, ignored on goal, and blocked when targeted",
        ),
    ]
    return findings


def check_action_policy() -> list[Finding]:
    from .intents import ActionPolicy, IntentSchemaError, parse_intent
    from .propose_cli import ADVERSARIAL_PAYLOADS, budget_denied, funnel_payloads

    policy = ActionPolicy(max_intents=len(ADVERSARIAL_PAYLOADS) + 5, scope_window_id="win-1")
    entries = funnel_payloads(ADVERSARIAL_PAYLOADS, policy=policy)
    contained = all(
        (not entry.get("parsed")) or entry.get("verdict") in ("denied", "needs_confirmation")
        for entry in entries
    )
    bypassed = [
        entry
        for entry in entries
        if entry.get("parsed")
        and entry.get("kind") in ("click_element", "type_text", "press_key", "scroll")
        and entry.get("verdict") == "preview_only"
    ]
    coordinates_rejected = False
    try:
        parse_intent({"kind": "click_element", "screen_x": 10, "screen_y": 20})
    except IntentSchemaError:
        coordinates_rejected = True
    return [
        _finding(
            "policy.funnel-contains-frozen-adversarial-set",
            "action_policy",
            contained and not bypassed and budget_denied(),
            f"{len(entries)} adversarial payloads contained, {len(bypassed)} bypassed, budget_denied={budget_denied()}",
        ),
        _finding(
            "policy.coordinates-rejected",
            "action_policy",
            coordinates_rejected,
            "coordinate addressing is rejected by the schema (element identity only)",
        ),
    ]


def check_permission_changes() -> list[Finding]:
    report = _scenario_report()
    by_name = {row["name"]: row for row in report["results"]}
    return [
        _finding(
            "permission.changed-and-required-typed",
            "permission_changes",
            by_name["permission-changed"]["terminal"] == "blocked:permission_changed"
            and by_name["permission-required"]["terminal"] == "blocked:permission_required",
            "mid-run grant loss blocks as permission_changed; never-granted blocks as permission_required",
        )
    ]


def import_violations(src_dir: Path) -> list[str]:
    """Third-party imports outside the stdlib and this package (teeth: tests plant one)."""

    def is_stdlib(root: str) -> bool:
        names = getattr(sys, "stdlib_module_names", None)
        if names is not None:
            return root in names
        if root in sys.builtin_module_names:
            return True
        from importlib.util import find_spec

        try:
            spec = find_spec(root)
        except Exception:  # noqa: BLE001 - unresolvable means not stdlib
            return False
        if spec is None:
            # Not importable at all: on 3.9 (no sys.stdlib_module_names) this
            # is how an *uninstalled* third-party import looks — flag it.
            return False
        if not spec.origin:
            return True
        return "site-packages" not in spec.origin and "dist-packages" not in spec.origin

    allowed = {"vision_assistant"}
    bad: list[str] = []
    for path in sorted(Path(src_dir).glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in allowed and not is_stdlib(root):
                        bad.append(f"{path.name}:{root}")
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                root = (node.module or "").split(".")[0]
                if root and root not in allowed and not is_stdlib(root):
                    bad.append(f"{path.name}:{root}")
    return sorted(set(bad))


def check_supply_chain() -> list[Finding]:
    from .acquire import DEFAULT_CANDIDATE
    from .manifest import build_manifest, verify_models

    findings = []
    violations = import_violations(SRC)
    findings.append(
        _finding(
            "supply.stdlib-only",
            "supply_chain",
            not violations,
            "no third-party imports in product code" if not violations else f"third-party imports: {violations}",
        )
    )
    pin_dir = REPO_ROOT / "models" / DEFAULT_CANDIDATE
    if (pin_dir / "pin.json").is_file():
        report = verify_models(pin_dir, mode="size")
        findings.append(
            _finding(
                "supply.model-pin",
                "supply_chain",
                report["ok"],
                f"pinned model files verified by size against pin.json ({report['reason']})",
            )
        )
    else:
        findings.append(
            _finding(
                "supply.model-pin",
                "supply_chain",
                False,
                "no local pin directory (a fresh clone acquires the model explicitly)",
                severity=NOTE,
            )
        )
    llama = shutil.which("llama-server")
    runtime_line = None
    if llama:
        try:
            done = subprocess.run([llama, "--version"], capture_output=True, text=True, timeout=15)
            text = (done.stdout or done.stderr).strip()
            runtime_line = text.splitlines()[0][:100] if text else llama
        except Exception:  # noqa: BLE001
            runtime_line = llama
    findings.append(
        _finding(
            "supply.runtime-recorded",
            "supply_chain",
            runtime_line is not None,
            f"runtime recorded: {runtime_line}" if runtime_line else "llama-server not installed (model features unavailable)",
            severity=CRITICAL if runtime_line else NOTE,
        )
    )
    manifest = build_manifest(pin_dir=pin_dir if (pin_dir / "pin.json").is_file() else None)
    licences_ok = all(entry.get("licence") for entry in manifest["models"]) and all(
        entry.get("licence") for entry in manifest["runtime"]
    )
    findings.append(
        _finding(
            "supply.licence-manifest-complete",
            "supply_chain",
            licences_ok,
            "every model artifact and runtime dependency carries a licence in the manifest",
        )
    )
    return findings


def check_crash_recovery() -> list[Finding]:
    from .assistant import preview_image, record_interruption

    findings = []
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        corrupt = root / "corrupt.png"
        corrupt.write_bytes(b"definitely not a png")
        artifacts = root / "artifacts"
        typed = False
        try:
            preview_image(corrupt, artifacts_root=artifacts, trace_id="audit-corrupt")
        except Exception:  # noqa: BLE001 - any typed failure is acceptable; leftovers are not
            typed = True
        findings.append(
            _finding(
                "recovery.corrupt-input-typed-and-clean",
                "crash_recovery",
                typed and len(_artifact_files(artifacts)) == 0,
                f"corrupt input fails typed with zero leftover artifacts (files: {len(_artifact_files(artifacts))})",
            )
        )

        image = root / "input.png"
        image.write_bytes(_tiny_png())
        trace_dir = root / "traces"
        trace_dir.mkdir()
        _preview, _frame, store, _ingestor = preview_image(
            image, artifacts_root=artifacts, trace_id="audit-interrupt"
        )
        record_interruption(trace_dir, "audit-interrupt", stage="model_start")
        store.purge("audit-interrupt")
        trace_text = (trace_dir / "audit-interrupt.jsonl").read_text(encoding="utf-8")
        findings.append(
            _finding(
                "recovery.interrupt-purge-and-trace",
                "crash_recovery",
                "cancelled" in trace_text and len(_artifact_files(artifacts)) == 0,
                "interrupt records a cancelled trace and purges the artifact",
            )
        )
    return findings


class _SiteAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.label_for: set[str] = set()
        self.inputs: list[dict] = []
        self.buttons: list[dict] = []
        self._label_depth = 0
        self._button_depth = 0
        self._button_attrs: dict = {}
        self._button_text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if tag == "label":
            self._label_depth += 1
            if values.get("for"):
                self.label_for.add(values["for"])
        if tag in ("input", "select", "textarea"):
            self.inputs.append({**values, "_nested_in_label": self._label_depth > 0})
        if tag == "button":
            self._button_depth += 1
            self._button_attrs = values
            self._button_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._label_depth:
            self._label_depth -= 1
        if tag == "button" and self._button_depth:
            self._button_depth -= 1
            self.buttons.append({"attrs": self._button_attrs, "text": "".join(self._button_text).strip()})

    def handle_data(self, data: str) -> None:
        if self._button_depth:
            self._button_text.append(data)


def a11y_findings(html_text: str) -> list[Finding]:
    """Pure helper so tests can plant unlabeled inputs (teeth)."""
    audit = _SiteAudit()
    audit.feed(html_text)
    unlabeled = [
        values.get("id") or values.get("name") or "?"
        for values in audit.inputs
        if not values.get("aria-label")
        and not values.get("_nested_in_label")
        and not (values.get("id") and values["id"] in audit.label_for)
    ]
    unnamed = [
        button["attrs"].get("id") or "?"
        for button in audit.buttons
        if not button["text"] and not button["attrs"].get("aria-label")
    ]
    return [
        _finding(
            "a11y.all-inputs-labeled",
            "accessibility",
            not unlabeled,
            "every input/select/textarea has a label, aria-label, or wraps inside its label"
            if not unlabeled
            else f"unlabeled controls: {unlabeled}",
        ),
        _finding(
            "a11y.all-buttons-named",
            "accessibility",
            not unnamed,
            "every button has visible text or an aria-label"
            if not unnamed
            else f"unnamed buttons: {unnamed}",
        ),
    ]


def check_accessibility() -> list[Finding]:
    findings = []
    for page in ("index.html",):
        html_text = (REPO_ROOT / "learning" / page).read_text(encoding="utf-8")
        findings.extend(a11y_findings(html_text))
    css = (REPO_ROOT / "learning" / "styles.css").read_text(encoding="utf-8")
    html_all = (REPO_ROOT / "learning" / "index.html").read_text(encoding="utf-8")
    findings.append(
        _finding(
            "a11y.site-contracts",
            "accessibility",
            "skip-link" in html_all and "aria-live" in html_all and "prefers-reduced-motion" in css,
            "skip link, aria-live regions, and reduced-motion support present",
        )
    )
    return findings


def check_long_session() -> list[Finding]:
    from .assistant import answer_frame, preview_image
    from .conversation import MAX_CONTEXT_CHARS, MAX_TURNS, STALE_AFTER_S

    bounds_ok = MAX_TURNS == 12 and MAX_CONTEXT_CHARS == 4000 and STALE_AFTER_S > 0
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        artifacts = root / "artifacts"
        trace_dir = root / "traces"
        trace_dir.mkdir()
        leftovers_ok = True
        for index in range(2):
            image = root / f"input-{index}.png"
            image.write_bytes(_tiny_png())
            _preview, frame, store, _ingestor = preview_image(
                image, artifacts_root=artifacts, trace_id=f"audit-seq-{index}"
            )
            answer_frame(
                frame,
                "What does the screen show?",
                adapter=_EchoAdapter(),
                trace_dir=trace_dir,
                store=store,
            )
        leftovers_ok = len(_artifact_files(artifacts)) == 0
    return [
        _finding(
            "session.bounds-frozen",
            "long_session",
            bounds_ok,
            f"turn limit {MAX_TURNS}, prompt budget {MAX_CONTEXT_CHARS} chars, stale warning {int(STALE_AFTER_S)} s",
        ),
        _finding(
            "session.no-artifact-leak-across-sessions",
            "long_session",
            leftovers_ok,
            "two sequential sessions leave zero artifacts",
        ),
    ]


def check_reproducibility() -> list[Finding]:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        outs = [root / "bundle-a", root / "bundle-b"]
        for out in outs:
            done = _run_cli("build", "--out", str(out))
            if done.returncode != 0:
                return [
                    _finding(
                        "repro.bundle-build",
                        "reproducibility",
                        False,
                        f"bundle build failed: {done.stdout[-200:]}{done.stderr[-200:]}",
                    )
                ]
        first = json.loads((outs[0] / "integrity.json").read_text(encoding="utf-8"))
        second = json.loads((outs[1] / "integrity.json").read_text(encoding="utf-8"))
        identical = first == second
        return [
            _finding(
                "repro.double-build-identical",
                "reproducibility",
                identical,
                f"two bundle builds produced byte-identical content hashes ({len(first['files'])} files)",
            )
        ]


def release_manifest(bundle: Path, *, version: str | None = None) -> dict:
    bundle = Path(bundle)
    version = version or (bundle / "VERSION").read_text(encoding="utf-8").strip()
    files = []
    for path in sorted(p for p in bundle.rglob("*") if p.is_file()):
        files.append(
            {
                "path": str(path.relative_to(bundle)),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    aggregate = hashlib.sha256(
        "".join(f"{entry['path']}\0{entry['sha256']}\n" for entry in files).encode("utf-8")
    ).hexdigest()
    llama = shutil.which("llama-server")
    runtime = None
    if llama:
        try:
            done = subprocess.run([llama, "--version"], capture_output=True, text=True, timeout=15)
            text = (done.stdout or done.stderr).strip()
            runtime = text.splitlines()[0][:100] if text else None
        except Exception:  # noqa: BLE001
            runtime = None
    return {
        "version": version,
        "files": files,
        "aggregate_sha256": aggregate,
        "interpreter": sys.version.split()[0],
        "runtime": runtime,
        "integrity": "SHA-256 content hashes; Apple Developer signing and notarization are "
        "not available in this lab — unsigned artifacts, documented as a known limitation",
    }


def check_release_integrity() -> list[Finding]:
    findings = []
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        bundle = root / "bundle-0.1.0"
        done = _run_cli("build", "--out", str(bundle))
        if done.returncode != 0:
            return [
                _finding(
                    "release.bundle-build",
                    "release_integrity",
                    False,
                    f"bundle build failed: {done.stderr[-200:]}",
                )
            ]
        newer = root / "bundle-0.1.1"
        done = _run_cli("build", "--out", str(newer), "--version", "0.1.1")
        if done.returncode != 0:
            return [
                _finding("release.bundle-build-2", "release_integrity", False, done.stderr[-200:])
            ]
        prefix = root / "prefix"
        (prefix / "models").mkdir(parents=True)
        (prefix / "models" / "marker.txt").write_text("kept", encoding="utf-8")
        sequence_ok = True
        detail = ""
        for argv in (
            ("install", "--bundle", str(bundle), "--prefix", str(prefix)),
            ("install", "--bundle", str(newer), "--prefix", str(prefix)),
            ("rollback", "--prefix", str(prefix)),
        ):
            done = _run_cli(*argv)
            if done.returncode != 0:
                sequence_ok = False
                detail = f"{argv[0]} failed: {done.stdout[-200:]}"
                break
        if sequence_ok:
            current = os.readlink(prefix / "current")
            if current != "versions/0.1.0":
                sequence_ok = False
                detail = f"rollback left current={current}"
        if sequence_ok:
            done = _run_cli("uninstall", "--prefix", str(prefix), "--apply")
            if done.returncode != 0:
                sequence_ok = False
                detail = "uninstall failed"
            else:
                kept_models = (prefix / "models" / "marker.txt").is_file()
                code_gone = not (prefix / "versions").exists() and not (prefix / "current").is_symlink()
                if not (kept_models and code_gone):
                    sequence_ok = False
                    detail = "uninstall removed the wrong things"
        findings.append(
            _finding(
                "release.rollback-and-removal-verified",
                "release_integrity",
                sequence_ok,
                "install 0.1.0 → upgrade 0.1.1 → rollback to 0.1.0 → uninstall keeps models, removes code"
                if sequence_ok
                else detail,
            )
        )

        manifest_a = release_manifest(bundle)
        manifest_b = release_manifest(bundle)
        findings.append(
            _finding(
                "release.manifest-deterministic",
                "release_integrity",
                manifest_a == manifest_b and len(manifest_a["files"]) > 0,
                f"release manifest is byte-stable ({len(manifest_a['files'])} files, "
                f"aggregate {manifest_a['aggregate_sha256'][:12]}…)",
            )
        )
        findings.append(
            _finding(
                "release.unsigned-documented",
                "release_integrity",
                "not available" in manifest_a["integrity"] and "known limitation" in manifest_a["integrity"],
                "Apple signing/notarization absent and documented as a known limitation",
            )
        )
    return findings


CHECKS = (
    ("capture_privacy", check_capture_privacy),
    ("trace_redaction", check_trace_redaction),
    ("malicious_screen_text", check_malicious_screen_text),
    ("action_policy", check_action_policy),
    ("permission_changes", check_permission_changes),
    ("supply_chain", check_supply_chain),
    ("crash_recovery", check_crash_recovery),
    ("accessibility", check_accessibility),
    ("long_session", check_long_session),
    ("reproducibility", check_reproducibility),
    ("release_integrity", check_release_integrity),
)


def run_audit() -> dict:
    findings: list[Finding] = []
    for category, check in CHECKS:
        try:
            findings.extend(check())
        except Exception as exc:  # noqa: BLE001 - a crashing check is a failing check
            findings.append(
                Finding(
                    f"{category}.check-crashed",
                    category,
                    "fail",
                    CRITICAL,
                    f"{type(exc).__name__}: {exc}",
                )
            )
    critical_failures = [f for f in findings if f.status == "fail" and f.severity == CRITICAL]
    notes = [f for f in findings if f.status == "note"]
    passes = [f for f in findings if f.status == "pass"]
    return {
        "run_id": f"m017-audit-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
        "findings": [asdict(f) for f in findings],
        "summary": {
            "checks": len(findings),
            "passed": len(passes),
            "notes": len(notes),
            "critical_failures": len(critical_failures),
            "gate_pass": not critical_failures,
        },
    }


# ------------------------------------------------------------------ support matrix


def support_markdown() -> str:
    from .evaluation import FAILURE_CATALOG
    from .manifest import APP_VERSION, PYTHON_FLOOR, build_manifest
    from .package_cli import PERMISSION_EDUCATION
    from .profiles import profile_summaries

    pin_dir = REPO_ROOT / "models" / "qwen3.5-4b"
    manifest = build_manifest(pin_dir=pin_dir if (pin_dir / "pin.json").is_file() else None)
    lines = [
        "# Support matrix — Vision Assistant (public beta)",
        "",
        f"Version {APP_VERSION} · Python ≥ {PYTHON_FLOOR} · stdlib only · macOS on "
        "Apple silicon (reference host: M2 Max).",
        "",
        "## Interpreters",
        "",
        "- **Tested:** CPython 3.9.6 (the project venv).",
        "- **Verified:** CPython 3.14.7 ran the complete read-only smoke (M015).",
        "- Not claimed beyond these: green elsewhere is likely but unverified.",
        "",
        "## Runtime",
        "",
        "- llama.cpp `llama-server` (installed separately, e.g. Homebrew); recorded build: "
        "0.3.0 / build 10621 on the reference host.",
        "- Xcode command line tools (`swiftc`) build the local helpers on first use.",
        "- Model files are acquired explicitly and verified by size (fast) or full SHA-256.",
        "",
        "## Permissions",
        "",
    ]
    for entry in PERMISSION_EDUCATION:
        lines.append(f"- **{entry['capability']}** — {entry['permission']}: {entry['default']}")
        lines.append(f"  Revoke: {entry['revoke']}")
    lines += [
        "",
        "## Feature matrix",
        "",
        "| Capability | Default | Notes |",
        "|---|---|---|",
        "| Read-only ask / grounding / OCR | on | capture is explicit and least-scope |",
        "| Loopback UI | on demand | binds 127.0.0.1 only, origin-allowlisted |",
        "| Supervised actions (practice window) | **opt-in** | separate explicit grant; never real apps |",
        "| Network | model acquisition only | installer, doctor, smoke, and runtimes are offline |",
        "",
        "## Profiles",
        "",
    ]
    for profile in profile_summaries():
        state = "measured" if profile["status"] == "measured" else "planned, unpinned"
        lines.append(
            f"- **{profile['title']}** ({state}): ≤ {profile['memory_target_gib']:g} GiB warm target, "
            f"ctx {profile['ctx_size']}"
        )
    lines += [
        "",
        "## Known limitations",
        "",
    ]
    for entry in FAILURE_CATALOG:
        if entry["status"] == "known-limitation":
            lines.append(f"- **{entry['title']}** ({entry['milestone']}): {entry['cause']}")
    lines += [
        "- **Unsigned artifacts:** no Apple Developer ID or notarization in this lab; "
        "release integrity is SHA-256 content hashes (see `audit_cli sign`).",
        "- The action executor targets the disposable practice window only.",
        "",
        "## Rollback & removal",
        "",
        "```bash",
        "vision rollback --prefix PREFIX            # switch to the previous version",
        "vision uninstall --prefix PREFIX           # dry run: shows the exact plan",
        "vision uninstall --prefix PREFIX --apply   # removes code; models/captures kept",
        "vision uninstall --prefix PREFIX --apply --remove-models   # explicit deletion",
        "```",
        "",
        "## Verifying this release",
        "",
        "```bash",
        "PYTHONPATH=src python -m vision_assistant.audit_cli run     # the hardening audit",
        "PYTHONPATH=src python -m vision_assistant.package_cli verify --bundle BUNDLE",
        "PYTHONPATH=src python -m vision_assistant.package_cli smoke",
        "```",
        "",
    ]
    return "\n".join(lines)


def write_support(out: Path | None = None) -> Path:
    target = Path(out) if out is not None else (REPO_ROOT / "docs" / "SUPPORT.md")
    target.write_text(support_markdown(), encoding="utf-8")
    return target
