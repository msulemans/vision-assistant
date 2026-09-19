"""M016 evaluation data: latency waterfall, failure catalog, model comparison,
exact reproduction commands, and the five teach-back tasks.

Everything here is data or pure functions — no I/O beyond reading a trace
file and writing the generated site payload. The committed
`learning/eval_data.js` is the golden output of `generate_site_data()`, so
the field manual cannot drift from the record it describes.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRACE = REPO_ROOT / "learning" / "data" / "canonical-turn.jsonl"
DEFAULT_SITE_DATA = REPO_ROOT / "learning" / "eval_data.js"

STAGE_LABELS = {
    "preview": "Capture handed to the pipeline",
    "model_started": "Prompt assembled; model begins",
    "answer": "Model finished generating",
    "done": "Trace closed; artifact released",
}


def load_trace(path: Path) -> dict:
    """Load a JSONL trace into memory (one event per line)."""
    events = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"trace line {number} is not JSON: {exc}") from exc
    if not events:
        raise ValueError(f"trace {path} contains no events")
    return {"path": str(path), "events": events}


def _first_ts(events: list[dict], event_type: str) -> float | None:
    for event in events:
        if event.get("type") == event_type:
            value = event.get("ts_ms")
            if isinstance(value, (int, float)):
                return float(value)
    return None


def latency_waterfall(trace: dict) -> dict:
    """Stage offsets of one turn: before-model, model, and record time."""
    events = trace["events"]
    preview = _first_ts(events, "preview")
    model_started = _first_ts(events, "model_started")
    answer = _first_ts(events, "answer")
    done = _first_ts(events, "done")
    if None in (preview, model_started, answer, done):
        raise ValueError("trace must contain preview, model_started, answer, and done events")
    done_payload = next(
        (event.get("payload", {}) for event in events if event.get("type") == "done"), {}
    )
    total_ms = round(done - preview, 1)
    raw_stages = (
        ("before-model", preview, model_started),
        ("model", model_started, answer),
        ("record", answer, done),
    )
    stages = []
    for name, start, end in raw_stages:
        duration = round(end - start, 1)
        stages.append(
            {
                "name": name,
                "start_ms": round(start - preview, 1),
                "duration_ms": duration,
                "share": round(duration / total_ms, 4) if total_ms > 0 else 0.0,
            }
        )
    model_stage = stages[1]
    return {
        "trace_id": trace["events"][0].get("trace_id"),
        "event_count": len(events),
        "total_ms": total_ms,
        "stages": stages,
        "model": {
            "stage_ms": model_stage["duration_ms"],
            "first_token_ms": done_payload.get("first_token_ms"),
            "complete_ms": done_payload.get("complete_ms"),
            "reported_total_ms": done_payload.get("total_ms"),
        },
    }


def ascii_waterfall(waterfall: dict, *, width: int = 46) -> str:
    """A terminal rendering of the waterfall (bars scaled to total)."""
    lines = [f"trace {waterfall['trace_id']} · total {waterfall['total_ms']} ms"]
    for stage in waterfall["stages"]:
        filled = max(1, round(stage["share"] * width))
        bar = "█" * filled + "·" * (width - filled)
        lines.append(f"  {stage['name']:>13s} {bar} {stage['duration_ms']:>8.1f} ms")
    model = waterfall["model"]
    lines.append(
        "  model detail: first token "
        f"{model['first_token_ms']} ms · complete {model['complete_ms']} ms"
    )
    return "\n".join(lines)


# ------------------------------------------------------------------ catalog

FAILURE_CATALOG: tuple[dict, ...] = (
    {
        "id": "f01-unsupported-claims",
        "milestone": "M004",
        "title": "Dialog answers over-claimed beyond the pixels",
        "symptom": "A dialog screenshot produced causal claims (a password problem) that no pixels supported.",
        "cause": "The model was asked a why-question; nothing in the pipeline separated visible facts from inference.",
        "fix": "[visible]/[inferred]/[unknown] labels, abstention scoring, and an unsupported-claim rate in the frozen gate.",
        "status": "fixed",
        "evidence": "2026-09-19-user-v4-results.json",
    },
    {
        "id": "f02-midword-substring",
        "milestone": "M012",
        "title": "\"AC\" matched \"Subtract\"",
        "symptom": "Grounding resolved the target \"AC\" to a Calculator button named Subtract (score 0.80).",
        "cause": "The substring scoring tier accepted mid-word sequences without a word boundary.",
        "fix": "Substring matches require a word boundary and at least four characters; frozen regression task (\"card\" must not match \"DISCARD\").",
        "status": "fixed",
        "evidence": "2026-09-19-m012-live-grounding.json",
    },
    {
        "id": "f03-black-capture",
        "milestone": "M013",
        "title": "Secondary-display window captured black",
        "symptom": "A window capture returned a near-uniform black PNG; the model reported it could not see anything.",
        "cause": "macOS can produce black captures for occluded/secondary-display windows.",
        "fix": "Near-uniform darkness is detected, replaced by a placeholder, and recorded as capture: black; the element list is declared authoritative.",
        "status": "fixed",
        "evidence": "2026-09-20-m013-supervised-execution.md",
    },
    {
        "id": "f04-frontmost-mismatch",
        "milestone": "M013",
        "title": "Synthetic keystrokes could never be aimed",
        "symptom": "Typing refused with frontmost_mismatch; nothing was typed.",
        "cause": "macOS 14+ ignores cross-app activation: NSRunningApplication.activate() reports success while frontmost never changes.",
        "fix": "Typing writes the identified element's value through the accessibility API and reads it back — no activation, no stray keystrokes.",
        "status": "fixed",
        "evidence": "2026-09-20-m013-attempt2-model.json",
    },
    {
        "id": "f05-blind-toggle",
        "milestone": "M013",
        "title": "A blind click toggled an already-on checkbox",
        "symptom": "The notify click turned an already-on checkbox off; verification correctly failed.",
        "cause": "The runner proposed and performed without first checking whether the task was already satisfied.",
        "fix": "already_done pre-check before any proposal — a satisfied task needs no action.",
        "status": "fixed",
        "evidence": "2026-09-20-m013-attempt1-model.json",
    },
    {
        "id": "f06-format-compliance",
        "milestone": "M011",
        "title": "The model would not emit JSON",
        "symptom": "Every task blocked with no_proposal; the model answered in prose despite repair prompts.",
        "cause": "Free-form decoding had no grammar; politeness is not a format.",
        "fix": "llama.cpp constrained decoding (response_format.json_schema) — valid intents on the first try.",
        "status": "fixed",
        "evidence": "2026-09-19-m011-simulated-loop.json",
    },
    {
        "id": "f07-context-overflow",
        "milestone": "M009",
        "title": "Large image exceeded the model context",
        "symptom": "llama-server returned 400: request (4252 tokens) exceeds context (4096).",
        "cause": "A 1800×2400 image encoded to more tokens than the configured context.",
        "fix": "Integer nearest-neighbour downscale (fit_for_model) to an empirical pixel budget before the model; OCR evidence stays full-res.",
        "status": "fixed",
        "evidence": "2026-09-19-m009-capstones.md",
    },
    {
        "id": "f08-leaked-artifact-on-stop",
        "milestone": "M006",
        "title": "Stop during model load leaked an artifact",
        "symptom": "Ctrl+C during adapter start produced a traceback and a leftover artifact.",
        "cause": "The interrupt handler assumed the model was already running.",
        "fix": "Stop path purges the artifact, records a cancelled trace, and exits 130 cleanly.",
        "status": "fixed",
        "evidence": "2026-09-19-m006-stop-check.md",
    },
    {
        "id": "f09-dispatcher-subcommand",
        "milestone": "M015",
        "title": "The installed dispatcher consumed its subcommand",
        "symptom": "vision doctor failed: package_cli received no arguments.",
        "cause": "The wrapper shifted the subcommand away before exec.",
        "fix": "Passthrough routes keep \"$@\"; behavioral tests now execute the real dispatcher.",
        "status": "fixed",
        "evidence": "2026-09-20-m015-packaging-offline.md",
    },
    {
        "id": "f10-size-mode-blindspot",
        "milestone": "M015",
        "title": "Size verification cannot see same-size corruption",
        "symptom": "A single flipped byte kept every size check green.",
        "cause": "Byte counts are not integrity.",
        "fix": "--full-hash recomputes SHA-256 and is the honest choice when certainty matters.",
        "status": "known-limitation",
        "evidence": "2026-09-20-m015-packaging-offline.md",
    },
    {
        "id": "f11-shallow-electron-tree",
        "milestone": "M012",
        "title": "Electron apps expose a shallow accessibility tree",
        "symptom": "A VS Code window dumped only window chrome; its internals were invisible.",
        "cause": "Electron exposes the full tree only after an accessibility-enhancement write, which this project refuses to perform.",
        "fix": "Documented limitation; grounding gates use apps that expose honest trees.",
        "status": "known-limitation",
        "evidence": "2026-09-19-m012-live-grounding.json",
    },
    {
        "id": "f12-small-text-misread",
        "milestone": "M007",
        "title": "\"UNSAVED REPORT\" misread at 1×",
        "symptom": "OCR at original scale produced '(UNSEVED BEFOBT)'.",
        "cause": "Small UI text is below reliable VNRecognizeTextRequest scale.",
        "fix": "Zoom ×2 before OCR (×4 regresses); the frozen pipeline is zoom → literal OCR → prompt.",
        "status": "fixed",
        "evidence": "2026-09-19-m007-ocr-smoke.md",
    },
)

# ------------------------------------------------------------------ comparison

COMPARISONS: tuple[dict, ...] = (
    {
        "name": "Qwen3.5-4B · Q4_K_M · llama.cpp · ctx 4096",
        "status": "selected",
        "held_out": "23/24 (≥ 0.95)",
        "rss_gib": 3.792,
        "first_p95_ms": 839,
        "notes": "M005 Phase-1 selection; the shipped pin. v4 prompt/decoding revision, thinking off.",
        "evidence": "2026-09-19-user-v4-results.json",
    },
    {
        "name": "Qwen3.5-4B · first llama-mtmd-cli run",
        "status": "losing run (preserved)",
        "held_out": "11/24",
        "rss_gib": None,
        "first_p95_ms": 7520,
        "notes": "Recall 0.79, unsupported 0.26, no abstention — the run that forced the pipeline redesign.",
        "evidence": "2026-09-19-user-v4-results.json",
    },
    {
        "name": "Gemma-3-4B IT · Q4_K_M",
        "status": "unpinned candidate",
        "held_out": None,
        "rss_gib": None,
        "first_p95_ms": None,
        "notes": "Listed in the acquisition registry with licence terms; no measured run.",
        "evidence": None,
    },
    {
        "name": "Qwen3-VL-8B-Instruct · Q4_K_M",
        "status": "unpinned candidate (quality profile)",
        "held_out": None,
        "rss_gib": None,
        "first_p95_ms": None,
        "notes": "Would require its own bake-off under the same frozen gates; not run.",
        "evidence": None,
    },
)

# ------------------------------------------------------------------ commands

REPRODUCTION_COMMANDS: tuple[dict, ...] = (
    {"milestone": "M002", "what": "Deterministic event spine round-trip", "command": "PYTHONPATH=src python -m vision_assistant.cli --verify", "speed": "seconds", "needs_model": False},
    {"milestone": "M004", "what": "Frozen corpus gold/bad verification", "command": "PYTHONPATH=src python -m vision_assistant.corpus_cli --freeze && PYTHONPATH=src python -m vision_assistant.corpus_cli --verify", "speed": "seconds", "needs_model": False},
    {"milestone": "M005", "what": "Bake-off contract and candidate registry", "command": "PYTHONPATH=src python -m vision_assistant.bakeoff_cli --plan", "speed": "seconds", "needs_model": False},
    {"milestone": "M006", "what": "One-shot assistant on any PNG", "command": "PYTHONPATH=src python -m vision_assistant.assistant_cli --image <screenshot.png>", "speed": "minutes", "needs_model": True},
    {"milestone": "M007", "what": "OCR evidence on the difficult subset", "command": "PYTHONPATH=src python -m vision_assistant.augment_cli --cases m004-dialog-14", "speed": "minutes", "needs_model": True},
    {"milestone": "M009", "what": "Loopback capture/ask UI", "command": "PYTHONPATH=src python -m vision_assistant.ui_server --open", "speed": "minutes", "needs_model": True},
    {"milestone": "M010", "what": "Intent schema and policy boundary", "command": "PYTHONPATH=src python -m unittest tests.test_intents", "speed": "seconds", "needs_model": False},
    {"milestone": "M012", "what": "Read-only grounding gate (44 checks)", "command": "PYTHONPATH=src python -m vision_assistant.grounding_cli --verify", "speed": "seconds", "needs_model": False},
    {"milestone": "M013", "what": "Supervised executor against the practice window", "command": "(runs/m013-tools/practice_window >/dev/null 2>&1 &) && PYTHONPATH=src python -m vision_assistant.supervised_cli", "speed": "minutes", "needs_model": True},
    {"milestone": "M014", "what": "Bounded agent: 22-scenario gate + interrupt p95", "command": "PYTHONPATH=src python -m vision_assistant.agent_eval", "speed": "seconds", "needs_model": False},
    {"milestone": "M014", "what": "Bounded agent with the pinned model", "command": "(runs/m013-tools/practice_window >/dev/null 2>&1 &) && PYTHONPATH=src python -m vision_assistant.agent_cli", "speed": "minutes", "needs_model": True},
    {"milestone": "M015", "what": "Offline smoke from an install (audit, models, 44/44)", "command": "~/vision-assistant/bin/vision smoke", "speed": "seconds", "needs_model": False},
    {"milestone": "M015", "what": "Full read-only reproduction with the model", "command": "~/vision-assistant/bin/vision smoke --with-model", "speed": "minutes", "needs_model": True},
)

# ------------------------------------------------------------------ teach-back

TEACH_BACK_TASKS: tuple[dict, ...] = (
    {
        "id": "tb1-trace-a-turn",
        "title": "Trace a visual turn",
        "gate_item": "trace a visual turn",
        "prompt": "Using the latency waterfall, walk one recorded turn stage by stage and name what each stage can and cannot promise.",
        "checklist": (
            "capture is explicit and least-scope before anything is read",
            "ingest normalizes the PNG privately and hashes it — the model never receives the file path",
            "before-model includes prompt assembly (and OCR evidence when enabled)",
            "the model stage measures first_token_ms and complete_ms separately",
            "the trace keeps counts and labels, never screen text",
            "the artifact is released by the done stage",
        ),
        "where": "Field manual → Latency waterfall; README trace sections",
        "hint": "Follow the four event types: preview → model_started → answer → done.",
    },
    {
        "id": "tb2-encoding-vs-generation",
        "title": "Encoding is not generation",
        "gate_item": "explain image encoding versus text generation",
        "prompt": "Explain how the screenshot becomes something the language model can read — and why 'the model sees the screen' is the wrong sentence.",
        "checklist": (
            "the image is encoded by a vision tower into embeddings, then projected into the language model's token space",
            "the projector (mmproj) is the bridge; the raw pixels are never 'understood' as an image by the decoder",
            "text is generated token by token with sampling — decoding, not retrieval",
            "first_token_ms measures time to the first decoded token; complete_ms covers the whole answer",
            "a bigger image costs tokens: the image budget and downscaling exist because of this",
        ),
        "where": "CURRICULUM M004–M005; field glossary (projector, inference)",
        "hint": "Two different machines: an encoder that compresses an image, a decoder that writes text.",
    },
    {
        "id": "tb3-diagnose-hallucination",
        "title": "Diagnose one hallucination",
        "gate_item": "diagnose one hallucination",
        "prompt": "Pick one entry from the failure explorer and reconstruct it: symptom, cause, the guard that now catches it, and the evidence file.",
        "checklist": (
            "the symptom is described in terms of labels (visible/inferred/unsupported), not vibes",
            "the cause names a pipeline gap, not 'the model is bad'",
            "the fix is a mechanism (scoring, boundary rule, detection, schema) with a regression test",
            "the evidence file is named and findable",
            "you can say which gate would go red if the fix were removed",
        ),
        "where": "Field manual → Failure explorer (try f01 or f02)",
        "hint": "Best entries to try: the password claim (f01) or AC/Subtract (f02).",
    },
    {
        "id": "tb4-add-a-fixture",
        "title": "Add a frozen fixture",
        "gate_item": "add a frozen fixture",
        "prompt": "Add one new case to the frozen corpus by the documented procedure, and explain why the hashes are allowed to change.",
        "checklist": (
            "new case follows the corpus case format (question, gold answer, category)",
            "corpus_cli --freeze regenerates the manifest deliberately — never silently",
            "corpus_cli --verify still passes gold/bad checks after the change",
            "the frozen-set change is recorded (VISION_STATE/evidence), because frozen means deliberate",
            "you can explain why editing a frozen case without a re-freeze would be a measurement bug",
        ),
        "where": "README corpus section; CURRICULUM M004",
        "hint": "Frozen is a promise: every deliberate change is visible in the diff.",
    },
    {
        "id": "tb5-no-direct-action",
        "title": "Why the model never owns an action",
        "gate_item": "explain why the model cannot directly own an action",
        "prompt": "Explain the path from a proposal to a performed action, and why every gate in that path exists.",
        "checklist": (
            "the model may only propose a typed intent; strict schema rejects coordinates and unknown fields",
            "policy disposes: budgets, scope, secrets — before any planning",
            "the plan binds the action to a stable element identity from a fresh read-only snapshot",
            "the user confirms, the freshness re-check runs, and only then does the single writer artifact post",
            "post-action observation verifies the expected state; unapproved_actions must stay 0",
            "budgets, takeover detection, and typed blocked states bound the agent loop",
        ),
        "where": "CURRICULUM M010–M014; README agent sections",
        "hint": "schema → policy → plan → preflight → confirm → recheck → perform → verify.",
    },
)


# ------------------------------------------------------------------ payload


def site_payload(trace_path: Path | None = None) -> dict:
    """The full field-manual payload embedded into learning/eval_data.js."""
    trace = Path(trace_path) if trace_path is not None else DEFAULT_TRACE
    return {
        "generated_from": str(trace.relative_to(REPO_ROOT))
        if trace.is_absolute() and str(trace).startswith(str(REPO_ROOT))
        else str(trace),
        "waterfall": latency_waterfall(load_trace(trace)),
        "failures": [dict(entry) for entry in FAILURE_CATALOG],
        "comparisons": [dict(entry) for entry in COMPARISONS],
        "commands": [dict(entry) for entry in REPRODUCTION_COMMANDS],
        "teach_back": [dict(entry) for entry in TEACH_BACK_TASKS],
    }


def generate_site_data(
    out_path: Path | None = None, *, trace_path: Path | None = None
) -> Path:
    """Write learning/eval_data.js deterministically (the golden output)."""
    target = Path(out_path) if out_path is not None else DEFAULT_SITE_DATA
    payload = site_payload(trace_path)
    body = (
        "// Generated by `PYTHONPATH=src python -m vision_assistant.evaluation_cli generate`.\n"
        "// Do not edit by hand; regenerate instead.\n"
        "window.VISION_EVAL = "
        + json.dumps(payload, indent=2, sort_keys=True)
        + ";\n"
    )
    target.write_text(body, encoding="utf-8")
    return target
