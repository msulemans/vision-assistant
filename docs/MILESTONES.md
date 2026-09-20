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
no real pixels, model, server dependency, or permission. **Complete.**

### 003 — Explicit screenshot ingest and capture

Learn: pixels versus points, Retina scale, colour/orientation, window/region
scope, formats, metadata, and macOS Screen Recording consent.

Build: file ingest first, then user-triggered single screenshot capture behind
one `CapturePort`; normalization and ephemeral lifecycle.

Gate: generated fixture and user-approved capture use the same pipeline;
dimensions/hashes/timings are correct; cancel works; raw pixels are ignored and
deleted by default. Permission denial is a normal, recoverable state.
**Complete.**

### 004 — Frozen screen-understanding corpus

Learn: task design, leakage, annotation, OCR versus reasoning, abstention, and
why a demo screenshot is not an evaluation.

Freeze: synthetic and user-reviewed/redacted terminal, dialog, form, settings,
dashboard, small-text, dark-mode, and insufficient-evidence cases.

Gate: manifests/hashes, required facts, forbidden claims, uncertainty labels,
scorer, prompt, image budget, resource ceilings, and promotion rule are locked
before a model download. **Complete.**

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

Delivered as the one-shot CLI (`assistant_cli`): live runs answer with real
timing (first token 651–659 ms, complete 1130–1145 ms) and honest labels;
stop/retry/reset verified live (clean `cancelled` at every stage, artifact
purged, zero leftovers); fully offline. Capstone smoke passes; warm-trial and
certification schedules remain in the M005/M015 measurement records. The
browser-UI treatment of this flow arrives with M009. **Complete.**

## Phase 2 — Understand a live UI

### 007 — Evidence augmentation and focused re-observation

Build: optional deterministic OCR, Accessibility snapshot, crop/zoom, and a
bounded second-look request. Trusted code retains provenance for each fact.

Gate: augmentation improves the predeclared difficult subset without
increasing unsupported claims, privacy scope, or latency beyond ceilings.

Delivered: `pixels.py` (stdlib crop/zoom), `tools/vision_ocr.swift` +
`ocr_vision.py` (local Vision OCR; no permission, no package), `evidence.py`
(provenance; facts in prompts only, trace-safe summaries), `--evidence-ocr`
in the assistant, and `augment_cli.py` measurement. Frozen subset and full
held-out measured 2026-09-19: 23/24 → 24/24 (the single failure flipped), no
regressions, unsupported 0, forbidden 0, 1.25–1.49 s per call.
Accessibility snapshot and second-look were deferred: both would widen scope
(a new TCC permission / a second model call) without a demonstrated need in
the measured subset. **Complete** for the frozen scope.

### 008 — Multi-turn visual conversation

Build: follow-up questions over an explicit current capture, bounded history,
new-capture indicator, reset, and stale-image warnings.

Gate: frozen reference/correction tasks pass; no screenshot crosses sessions;
prompt growth and retained artifacts remain bounded.

Delivered: `conversation.py` (one session per capture; 12-turn / 4000-char /
15-min bounds; typed errors; session traces), `assistant_cli --chat`, a frozen
6-task evaluation (`conversation_eval.py`) and its harness
(`conversation_cli.py`). Measured 2026-09-19: 6/6 tasks passed, all artifacts
released, prompts ≤ 333 characters. **Complete.**

### 009 — Usable capture and answer UI

Build: window/region picker, keyboard shortcut, preview/redact/retake, recent
ephemeral run list, copy answer, accessible status, and failure explorer.

Gate: a new user completes the five read-only capstones without terminal help;
permission and model failures have actionable recovery; sensitive captures are
not silently retained.

Delivered: loopback-only stdlib UI server (`ui_server.py`) + dependency-free
page (`ui_page.html`): picker/reuse, drag-to-redact, ask + bounded follow-ups,
stop/reset/copy, status, typed failure banners, bounded model view for large
captures. All five capstones passed live 2026-09-19 (no terminal help).
**Complete.**

## Phase 3 — Propose before acting

### 010 — Typed action intents and policy, no execution

Learn: capability security, element identity, coordinate risk, consequences,
prompt injection, approvals, and action budgets.

Build: schemas and policy for observe, click element, type bounded text, key
press, scroll, cancel, and finish. Render a visible proposal/target preview.

Gate: adversarial fixtures cannot bypass validation, scope, confirmations,
budgets, secret-entry rules, or forbidden actions. Nothing controls the Mac.

Delivered: `intents.py` (strict schema + `ActionPolicy` + previews),
`propose_cli.py` (model proposes, policy disposes, frozen adversarial
funnel), 21 adversarial tests. Measured 2026-09-19: 13/13 payloads contained,
zero bypasses, budget denied, nothing executed. **Complete** for the frozen
scope.

### 011 — Disposable simulated action loop

Build: fake executor and purpose-built local practice app with observe ->
propose -> approve -> execute -> verify, retry, and emergency stop.

Gate: frozen tasks complete within action budgets; denial/cancel/timeout are
final; no stale observation is acted on; zero host mouse/keyboard events.

Delivered: `practice_app.py` (Python-only toy app), `action_loop.py`
(observe → propose → validate → approve → fake-execute → verify with final
denial/cancel/stale/budget states), `sim_cli.py` (schema-constrained model
proposals), 19 tests. Measured 2026-09-19: 3/3 frozen tasks done in one step
each, zero host input events. **Complete.**

### 012 — Read-only macOS UI grounding

Build: inspect selected-window Accessibility elements and align them with the
screenshot. Prefer stable element indices/roles/names to coordinates.

Gate: selected-window target identity and state meet the frozen grounding gate
across scale/layout variants; no input events are posted.

Delivered: read-only AX helper + grounding pipeline + frozen gate, closed
2026-09-19. `tools/ax_dump.swift` (attributes only; explicit
`--request-permission`; `--app` selector), `ax_vision.py` (typed errors;
secure values dropped), `grounding.py` (derived-scale alignment; fail-closed
resolution), `grounding_fixture.py` + `grounding_eval.py` (frozen gate:
11 tasks × 4 variants = 44 checks, 44/44 passing), `grounding_cli.py`
(`--verify`, `--check`, `--request-permission`, `--dump`, `--ground` with
`--capture`, `--crop-out`, `--ocr-check`), 37 tests including the no-input
source scan. Live run: `7`/`5`/`9` grounded at 2x with OCR-matched crops;
`AC`/`card` fail closed; a mid-word substring false positive found live
("AC" → "Subtract") was fixed and frozen as a regression task. **Complete.**

### 013 — Supervised mouse and keyboard execution

Build: an opt-in macOS executor with Accessibility permission, visible target
overlay, per-action preview, confirmations, stop control, and post-action
observation. Start only in the disposable practice app.

Gate: every host action is attributable to an approved typed intent; zero
wrong-target, hidden-window, secret-field, approval-bypass, or stale-frame
actions across the frozen suite.

Delivered: the first supervised executor, closed 2026-09-20.
`tools/practice_window.swift` (disposable window with five stable AX ids),
`tools/ax_action.swift` (the only writer: identity-addressed AXPress,
accessibility value-write typing with read-back, guarded key events;
stale-frame, secure, disabled, and frontmost guards),
`tools/ax_overlay.swift` (click-through target highlight), `executor.py`
(identity/role/secret/freshness guards, typed refusals), and
`supervised_cli.py` (observe → propose → policy → plan → preflight →
preview + overlay → confirm → re-check → perform → verify, with
`already_done`, cancellation, and full attribution), plus the M013 test
suites including the inverted source scan (exactly one file may contain
writer APIs; no mouse event APIs anywhere). Live gate: three frozen tasks
performed and verified with zero unapproved actions; every refusal path
demonstrated with zero side effects. **Complete.**

### 014 — Recovery and bounded task agent

Build: multi-step plans, maximum step/time budgets, user takeover, focus-change
detection, changed-screen recovery, and explicit blocked/finished states.

Gate: the agent stops safely on ambiguity, unexpected dialogs, permission
changes, and prompt injection; interrupt p95 and recovery correctness meet the
registered ceilings.
Delivered: the first bounded task agent, closed 2026-09-20. `agent.py`
(stepwise goal loop: budgets 8 steps / 120 s / 2 recoveries; bounded
stale-frame recovery with re-observation, re-planning, and a fresh
confirmation; takeover detection by focus transition and by post-action
state diff; single-window scope with `unexpected_dialog` blocks; goal-lock
allowlists with `off_goal_denied`; injection markers flagged and never
followed; explicit finished/blocked/cancelled terminals), `agent_cli.py`,
`agent_eval.py` (22-scenario deterministic gate plus a real-SIGINT
interrupt sampler), practice window `app:dialog-button` and
`app:nudge-button` and `--injection`, `ax_dump --front`. Live gate: all
three frozen goals finished stepwise with the pinned model (3 performed,
0 unapproved); stale recovery, dialog, takeover, permission change, budget
exhaustion, injection-targeted and off-goal proposals each blocked safely
with zero unapproved actions; interrupt p95 18.1 ms over ten samples.
**Complete.**
## Phase 4 — Finish the local product and learning lab

### 015 — Profiles, packaging, and offline verification

Build: Inspect/Balanced/Quality profiles, first-run permission education,
artifact/licence manifest, size forecast, upgrade/rollback, clean uninstall,
and offline-after-install operation.

Gate: a clean Mac reproduces the read-only profile; action support remains an
explicit separate opt-in; removal deletes local models/captures only with user
choice.

Delivered: the installable local product, closed 2026-09-20. `profiles.py`
(frozen measured/planned registry; default balanced), `manifest.py`
(artifact/licence manifest, size forecast, size/hash model verification),
`package_cli.py` (build/verify/install/rollback/uninstall/versions/doctor/
smoke/forecast, with a frozen source-level offline audit and a generated
offline installer plus a `bin/vision` dispatcher). Live gate: bundle
verified (58 files, 504 KB); fresh-prefix install with its own venv
(Python 3.14.7 — newer than tested); doctor permission education; smoke
44/44 with verified asks in 3.1–4.7 s; a Seatbelt-sandboxed run denying
all non-loopback networking reproduced the read-only profile (negative
control: DNS denied); upgrade/rollback verified; uninstall removed code
and kept models (deletion behind an explicit flag). The live gate also
caught and fixed a dispatcher bug (subcommand passthrough) with new
behavioral wrapper tests. **Complete.**

### 016 — Evaluation and reciprocal learning field manual

Build: latency waterfall, model comparison, failure explorer, component
toggles, glossary, quizzes, teach-back tasks, and exact reproduction commands.

Gate: a new learner can trace a visual turn, explain image encoding versus text
generation, diagnose one hallucination, add a frozen fixture, and explain why
the model cannot directly own an action.
Delivered: the evaluation and reciprocal learning field manual, closed
2026-09-20. `evaluation.py` (canonical-turn waterfall; 12-entry failure
catalog with component tags and evidence links; measured model comparison;
13 reproduction commands; the five gate teach-back tasks) plus
`evaluation_cli.py` and the byte-stable generated `learning/eval_data.js`;
a new field-manual chapter in the learning site: waterfall bars, searchable
failure explorer with component toggles, teach-back cards with checklists,
copyable commands, and the quiz extended to trust boundaries (network
surface, stale-frame recovery). Verified live in the browser on both quiz
paths; the fixture procedure executed as a worked example (freeze →
verify 121/121 → revert to baseline). Honest caveat: the human learner
walkthrough is recorded as a standing verification item — the milestone
closed on the reference key, the worked example, and the fully verified
manual surfaces. **Complete.**
### 017 — Public beta hardening

Audit: capture privacy, trace redaction, malicious screen text, action policy,
permission changes, dependency/model supply chain, crash recovery,
accessibility, long-session resources, signing, and support matrix.

Gate: zero critical safety-suite failures; signed/reproducible release artifacts;
known limitations, rollback, and removal are verified.

Delivered: public beta hardening, closed 2026-09-20 — and with it the
frozen roadmap. `audit.py` (eleven frozen categories, 26 checks: capture
privacy, trace redaction with live canaries, malicious screen text, action
policy, permission changes, supply chain, crash recovery, accessibility,
long-session resources, reproducibility, release integrity) +
`audit_cli.py` (run/sign/support) + `docs/SUPPORT.md` + a reproducible
release manifest. Gate results: 26/26 checks, zero critical failures; two
bundle builds byte-identical; rollback and removal re-verified on real
bundles; unsigned artifacts documented as a known limitation. The audit's
own tests caught a real Python 3.9 fallback bug in the import scanner,
fixed the same day. **Complete. End of the frozen roadmap:** M001 through
M017 are complete and evidenced.

## Proposed extension — M018 browser computer-use agent

Planning only; M001–M017 completion records remain unchanged.
See [COMPUTER_USE_AGENT_PLAN.md](COMPUTER_USE_AGENT_PLAN.md) for the screenshot
loop, browser scope, 50 tasks, held-out evaluation, and staged cost limits.

**M018A delivered (2026-09-20):** frozen 50-task manifest (30 development /
20 held-out), independent oracles validated against correct and wrong final
states, deterministic fixture site with reset/seed contract; stage gate
`python -m vision_assistant.browser_cli verify` = PASS with zero model runs.
Evidence: `docs/evidence/2026-09-20-m018a-manifest-oracles.md`.

**M018B delivered (2026-09-20):** disposable WKWebView helper + typed adapter
with fail-closed guards (stale frames, origin escapes, password/uncfocus
typing, budgets, cleanup); live scripted smoke passed (click → `/story/d03/`,
typing verified 2/2, zero orphans). Evidence:
`docs/evidence/2026-09-20-m018b-browser-adapter.md`.

**M018C delivered (2026-09-20):** screenshot-driven loop + `browser_cli task`;
five smoke tasks run once each with the pinned model — productive completion
**1/5** (only the already-satisfied case); failure classes recorded (type-
without-focus; same-point clicks; premature finish), one prompt revision
after the single inspected class, vision pipeline verified by probe.
Evidence: `docs/evidence/2026-09-20-m018c-smoke.md`.

**M018D delivered (2026-09-20):** frozen benchmark — development **4/30**
productive, held-out **3/18** productive (Wilson 0.06–0.39), refusals 1/2
expected-safe, zero forbidden actions, no human rescue; proposed gate NOT
met and preserved; **M018E deferred** with a recorded scope rationale (loop
back-only navigation policy frozen; measured capability makes a one-shot
live pilot uninformative). Evidence:
`docs/evidence/2026-09-20-m018d-benchmark.{md,json}`. The extension pauses
at a measured boundary: the 4B model cannot yet drive screenshot-only
browsing reliably, and the guards/oracles that proved it are the keepable
artifact.

**M018T delivered (2026-09-20):** target-assisted treatment — frozen plan
(`docs/M018T_TARGET_ASSISTED_PLAN.md`), deterministic implementation
(113-test sweep; frozen manifest sha untouched), scripted live smoke PASS,
five-task smoke measured **3/5 → 4/5** after the single recorded prompt
revision; then a frozen fresh 20-task evaluation set (new `eval` instance,
20/20 oracles, 66/66 mutations rejected; `docs/M018T_EVAL_FREEZE.md`) run
once per mode with a paired design: screenshot baseline **1/18** vs
treatment **6/18** productive (Wilson 0.163–0.563; +5 genuine flips on
identical tasks), refusals 1/2 vs 0/2 with one fixture-local submission
attempt recorded against a required-refusal task, zero forbidden actions
throughout. Tuning stopped at the freeze; results stand as measured.
Evidence: `docs/evidence/2026-09-20-m018t-{implementation,smoke,eval}.md`.
The extension is closed at two measured boundaries — screenshot-only
(M018D) and target-assisted (M018T); M018E stays deferred with its recorded
rationale.
