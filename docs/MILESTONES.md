# Milestones and gates

Only the current milestone may be implemented. A documented future design is
not permission to bundle it into the current milestone.

## Phase 1 — See one image reliably

### 001 — Project contract, research, and environment

Learn: multimodal pipeline boundaries, local/privacy claims, image-token cost,
evidence versus inference, runtime/model licences, and macOS permission scope.

Build: canonical state, architecture, metrics, research ledger, curriculum,
safe ignore rules, full roadmap, and read-only environment inventory.

Gate: the host and hypotheses are recorded; no package/model/capture/permission
is acquired. **Complete.**

### 002 — Deterministic event spine and browser shell

Learn: event envelopes, state machines, streaming, cancellation, timeouts, and
why UI observability precedes real AI.

Build: typed ports, fake clock, fake capture/model, synthetic image fixture,
JSONL trace, and a dependency-free browser UI.

Gate: success/failure/cancel/timeout traces are exact and round-trip; the UI
shows scope, preview, question, status, answer, evidence labels, and timings;
no real pixels, model, server dependency, or permission.

### 003 — Explicit screenshot ingest and capture

Learn: pixels versus points, Retina scale, colour/orientation, window/region
scope, formats, metadata, and macOS Screen Recording consent.

Build: file ingest first, then user-triggered single screenshot capture behind
one `CapturePort`; normalization and ephemeral lifecycle.

Gate: generated fixture and user-approved capture use the same pipeline;
dimensions/hashes/timings are correct; cancel works; raw pixels are ignored and
deleted by default. Permission denial is a normal, recoverable state.

### 004 — Frozen screen-understanding corpus

Learn: task design, leakage, annotation, OCR versus reasoning, abstention, and
why a demo screenshot is not an evaluation.

Freeze: synthetic and user-reviewed/redacted terminal, dialog, form, settings,
dashboard, small-text, dark-mode, and insufficient-evidence cases.

Gate: manifests/hashes, required facts, forbidden claims, uncertainty labels,
scorer, prompt, image budget, resource ceilings, and promotion rule are locked
before a model download.

### 005 — Local VLM and runtime bake-off

Compare: a 4B Apache-2.0 unified VLM hypothesis (initially Qwen3.5-4B), one
second 4B-class architecture, portable `llama.cpp` versus Apple `mlx-vlm`, and
only then a <=9B quality control if needed. Ollama may be a convenience control.

Gate: promote the smallest configuration meeting frozen correctness,
unsupported-claim, abstention, latency, memory, CPU/energy, swap, licence, and
artifact-size rules. Pin all revisions, hashes, quantization, prompts, and image
settings; preserve losing results.

### 006 — One-shot local Vision Assistant

Build: selected screenshot + typed question -> streamed local answer in the
browser UI with evidence/inference/unknown sections and trace waterfall.

Gate: all frozen capstone categories pass three consecutive warm trials;
cold/warm and p50/p95 evidence are recorded; deterministic and real-local runs
remain visibly distinct.

## Phase 2 — Understand a live UI

### 007 — Evidence augmentation and focused re-observation

Build: optional deterministic OCR, Accessibility snapshot, crop/zoom, and a
bounded second-look request. Trusted code retains provenance for each fact.

Gate: augmentation improves the predeclared difficult subset without
increasing unsupported claims, privacy scope, or latency beyond ceilings.

### 008 — Multi-turn visual conversation

Build: follow-up questions over an explicit current capture, bounded history,
new-capture indicator, reset, and stale-image warnings.

Gate: frozen reference/correction tasks pass; no screenshot crosses sessions;
prompt growth and retained artifacts remain bounded.

### 009 — Usable capture and answer UI

Build: window/region picker, keyboard shortcut, preview/redact/retake, recent
ephemeral run list, copy answer, accessible status, and failure explorer.

Gate: a new user completes the five read-only capstones without terminal help;
permission and model failures have actionable recovery; sensitive captures are
not silently retained.

## Phase 3 — Propose before acting

### 010 — Typed action intents and policy, no execution

Learn: capability security, element identity, coordinate risk, consequences,
prompt injection, approvals, and action budgets.

Build: schemas and policy for observe, click element, type bounded text, key
press, scroll, cancel, and finish. Render a visible proposal/target preview.

Gate: adversarial fixtures cannot bypass validation, scope, confirmations,
budgets, secret-entry rules, or forbidden actions. Nothing controls the Mac.

### 011 — Disposable simulated action loop

Build: fake executor and purpose-built local practice app with observe ->
propose -> approve -> execute -> verify, retry, and emergency stop.

Gate: frozen tasks complete within action budgets; denial/cancel/timeout are
final; no stale observation is acted on; zero host mouse/keyboard events.

### 012 — Read-only macOS UI grounding

Build: inspect selected-window Accessibility elements and align them with the
screenshot. Prefer stable element indices/roles/names to coordinates.

Gate: selected-window target identity and state meet the frozen grounding gate
across scale/layout variants; no input events are posted.

### 013 — Supervised mouse and keyboard execution

Build: an opt-in macOS executor with Accessibility permission, visible target
overlay, per-action preview, confirmations, stop control, and post-action
observation. Start only in the disposable practice app.

Gate: every host action is attributable to an approved typed intent; zero
wrong-target, hidden-window, secret-field, approval-bypass, or stale-frame
actions across the frozen suite.

### 014 — Recovery and bounded task agent

Build: multi-step plans, maximum step/time budgets, user takeover, focus-change
detection, changed-screen recovery, and explicit blocked/finished states.

Gate: the agent stops safely on ambiguity, unexpected dialogs, permission
changes, and prompt injection; interrupt p95 and recovery correctness meet the
registered ceilings.

## Phase 4 — Finish the local product and learning lab

### 015 — Profiles, packaging, and offline verification

Build: Inspect/Balanced/Quality profiles, first-run permission education,
artifact/licence manifest, size forecast, upgrade/rollback, clean uninstall,
and offline-after-install operation.

Gate: a clean Mac reproduces the read-only profile; action support remains an
explicit separate opt-in; removal deletes local models/captures only with user
choice.

### 016 — Evaluation and reciprocal learning field manual

Build: latency waterfall, model comparison, failure explorer, component
toggles, glossary, quizzes, teach-back tasks, and exact reproduction commands.

Gate: a new learner can trace a visual turn, explain image encoding versus text
generation, diagnose one hallucination, add a frozen fixture, and explain why
the model cannot directly own an action.

### 017 — Public beta hardening

Audit: capture privacy, trace redaction, malicious screen text, action policy,
permission changes, dependency/model supply chain, crash recovery,
accessibility, long-session resources, signing, and support matrix.

Gate: zero critical safety-suite failures; signed/reproducible release artifacts;
known limitations, rollback, and removal are verified.
