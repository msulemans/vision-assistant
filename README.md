# Local Vision Assistant Lab

Build a private assistant that can look at a selected screenshot, accept a
question, and explain what is visible:

```text
selected screen/window -> privacy boundary -> normalized image
                       -> local vision model + question -> grounded answer
```

Later, after the observation path is measured and trustworthy, extend it into
a supervised computer-use loop:

```text
observe -> propose typed action -> policy + user approval -> execute -> observe
```

This is both a product project and a learning lab. Every capability must have a
lesson, deterministic evidence, a labelled real-device measurement, and an
honest failure record.

## Direct answer

The correct first product is **screenshot question answering**, not an
autonomous mouse agent. We will first prove that capture is explicit, private,
fast, and accurate on frozen UI/error screenshots. Action support comes later
through typed, policy-checked operations with visible approval and an emergency
stop.

The reference machine is an Apple M2 Max MacBook Pro with 32 GB unified memory.
The initial model hypothesis is a quantized 4B-class multimodal model. A 9B
candidate is a quality control only if the smaller option misses the frozen
accuracy gate. No model is promoted from parameter count or public benchmarks.

## Product promise

The first useful capstone should answer questions such as:

- "Why is this application failing?" from a terminal or error dialog.
- "What should I click next?" from a settings or setup screen.
- "Which field is invalid?" from a form with visible validation feedback.
- "What changed between these two screens?" from before/after captures.
- "Summarize the important status on this dashboard."

An answer must distinguish visible evidence from inference. If the screenshot
does not contain enough evidence, the assistant should say so and ask for a
more useful capture instead of inventing a cause.

## Project rules

- Local inference is the product path. Hosted inference may be a labelled
  comparison only.
- Capture is user-initiated and visibly scoped to a chosen window, region, or
  display.
- Screenshots are ephemeral by default and never committed.
- Do not capture hidden windows, background apps, or a full display when a
  smaller selection is sufficient.
- Logs store metrics and redacted metadata, not raw pixels or sensitive text by
  default.
- The model may describe or propose an action; trusted code owns validation,
  policy, confirmation, execution, budgets, and stop reasons.
- No raw shell tool and no unrestricted mouse/keyboard interface is exposed to
  a model.
- Prefer Accessibility element identities to pixel coordinates. Coordinate
  actions are a later, riskier fallback.
- Preserve failed runs and negative model comparisons.
- Implement and verify exactly one milestone at a time.
- Do not download a model or install a dependency until the bake-off is frozen.

## Where to start

1. Read [VISION_STATE.md](VISION_STATE.md), the canonical project record.
2. Read [docs/MILESTONES.md](docs/MILESTONES.md); only the current milestone may
   be implemented.
3. Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
   [docs/METRICS.md](docs/METRICS.md).
4. Use [learning/CURRICULUM.md](learning/CURRICULUM.md) to learn the system in
   the same order it is built.
5. Open the interactive field manual:

   ```bash
   python scripts/serve_learning_lab.py
   # open http://127.0.0.1:4173/
   ```

   It also opens directly from `learning/index.html` without a server. The site
   teaches the same verified milestones, evidence, failures, and boundaries as
   the canonical state; it is not a separate marketing page.
6. Run the read-only inventory:

   ```bash
   ./scripts/check_environment.sh
   ```

## Current status

Milestone 001 is complete: the learning contract,
architecture boundary, metrics, research baseline, host inventory, privacy
rules, and end-to-end roadmap are recorded. No model, dependency, screenshot,
or permission was acquired. The repository is initialized on `main`.

Milestone 002 is complete: a deterministic event spine, fake clock,
fake capture/model adapters, a JSONL trace, and a dependency-free browser UI
using synthetic fixtures only. Byte-identical, round-tripping
success/failure/cancel/timeout traces were verified (see
`VISION_STATE.md`).

Milestone 003 is complete: dependency-free PNG ingest, bounded validation,
metadata stripping, private artifacts, default deletion, and the macOS
region/window selector all pass. Two user-selected live captures were
validated and deleted by default.

Milestone 004 is complete: a 48-case frozen screen-understanding corpus
(24 dev + 24 held-out across 8 categories), a deterministic answer scorer, and a
frozen prompt/image/resource contract — locked before any model download.

Milestone 005 is complete: the pinned local candidate (Qwen3.5-4B Q4_K_M,
llama.cpp, thinking off, ctx 4096) passed the frozen held-out gate and the
balanced resource ceiling; release-grade certification is deferred to
packaging (M015). See `VISION_STATE.md` for the outcome.

Milestones 006–012 are complete: one-shot assistant, OCR evidence
augmentation (held-out 24/24), bounded multi-turn chat (6/6), the loopback
UI with all five read-only capstones passing live, typed intent policy
containment (13/13 adversarial, zero bypasses), a simulated action loop
(3/3 tasks, zero host input), and read-only Accessibility grounding (frozen
gate 44/44; live targets grounded at 1x and 2x with OCR-verified crops; no
input events posted). Milestone 013 adds the first supervised executor:
three frozen tasks performed and verified against the disposable practice
window with zero unapproved actions, and every refusal path (unknown
element, coordinates, secret target, declined, stale frame, cancellation)
demonstrated live with nothing posted. Milestone 014 adds the bounded task
agent: step/time budgets, bounded stale-frame recovery, user-takeover
detection, unexpected-dialog and injection blocks, goal-lock allowlists,
and explicit finished/blocked/cancelled terminals. Measured 2026-09-20:
22/22 frozen deterministic scenarios; all three frozen goals finished
stepwise with the pinned model (zero unapproved); stale recovery, dialog,
takeover, permission change, budget, injection-targeted, and off-goal all
demonstrated live with zero unapproved actions; interrupt p95 18.1 ms.
Milestone 015 makes the lab installable: a versioned bundle with a frozen
offline audit installs into a fresh prefix with its own venv; doctor
explains every permission on first run; smoke reproduces the read-only
profile — audit, model verification, grounding 44/44, and a verified
one-shot ask — including under a sandbox that denies all non-loopback
networking; upgrade/rollback and a choiceful uninstall are verified.
Milestone 016 turns the learning lab into an evaluation instrument: a real
turn's latency waterfall (99.94% model), a 12-entry failure catalog with
component toggles, the losing run kept beside the selection, five
teach-back tasks, and exact reproduction commands. Milestone 017 closes
the roadmap with public-beta hardening: an eleven-area audit (26 checks,
zero critical failures), byte-identical bundle builds, a byte-stable
release manifest, a support matrix with documented limitations (unsigned
artifacts), and a re-verified rollback/removal story.
Roadmap complete: M001–M017. See `docs/SUPPORT.md` and
`docs/evidence/2026-09-20-m017-*.json`.

## Run the Milestone 002 lab

The lab is stdlib-only, so no package is installed.

```bash
PYTHONPATH=src python -m vision_assistant.cli --verify   # write traces + UI, verify
open ui/index.html                                        # dependency-free static UI
PYTHONPATH=src python -m unittest discover -s tests -v     # regression suite
```

Generated traces live in `runs/` and the synthetic fixture in
`runs/fixtures/`; both are Git-ignored.

## Learning website

The local field manual is a first-class project surface:

```bash
python scripts/serve_learning_lab.py
```

It currently covers the M001 contract, the interactive M002 event spine, the
M003 PNG custody path and pending live gate, all 17 roadmap milestones, the
preserved selector-timeout failure, glossary, flashcards, quiz, and teach-back
prompts. Update it with code, tests, state, and docs at every milestone.

## Run the Milestone 003 capture gate

```bash
PYTHONPATH=src python -m vision_assistant.capture_cli --verify
PYTHONPATH=src python -m vision_assistant.capture_cli --file /path/to/selected.png
PYTHONPATH=src python -m vision_assistant.capture_cli --interactive
```

`--interactive` opens the macOS selector only after you run the command. Select
one harmless region/window or press Escape. The normalized artifact is deleted
after validation unless you explicitly add `--retain`. Milestone 003 accepts
PNG only; JPEG/HEIC conversion and resizing are deliberately not hidden inside
this dependency-free gate.

## Run the Milestone 004 corpus gate

```bash
PYTHONPATH=src python -m vision_assistant.corpus_cli --freeze
PYTHONPATH=src python -m vision_assistant.corpus_cli --verify
```

`--freeze` writes the 48 fixtures, the corpus manifest (image SHA-256 and
dimensions), and the frozen config under `runs/m004-corpus/` (Git-ignored); the
committed generator is the deterministic source of truth. `--verify` confirms
byte-stable regeneration, that all 48 gold answers pass the scorer, and that all
48 confident-wrong answers fail.

## Run the Milestone 005 bake-off harness

```bash
PYTHONPATH=src python -m vision_assistant.bakeoff_cli --plan
PYTHONPATH=src python -m vision_assistant.bakeoff_cli --verify
```

`--plan` prints the frozen bake-off contract and the candidate registry
(candidate revisions/hashes are `"to-pin"` until each artifact is acquired).
`--verify` runs the deterministic harness with fake candidates to prove the
harness and promotion rule before any real model is downloaded.

Acquire and run a real candidate:

```bash
PYTHONPATH=src python -m vision_assistant.acquire plan
PYTHONPATH=src python -m vision_assistant.acquire download   # downloads the pinned GGUF + mmproj
PYTHONPATH=src python -m vision_assistant.acquire check      # verify sizes + SHA-256
PYTHONPATH=src python -m vision_assistant.bakeoff_cli --real --pin-dir models/qwen3.5-4b
PYTHONPATH=src python -m vision_assistant.bakeoff_cli --real --server --pin-dir models/qwen3.5-4b   # persistent, streaming
```

### M005 outcome (2026-09-19)

Qwen3.5-4B (Q4_K_M, llama.cpp, thinking off, context 4096) is the selected
Phase-1 configuration: the frozen v4 held-out run passes the 0.95 pass-rate
gate (23/24) and every measured ceiling (RSS 3.792 GiB, swap 0, acquisition
6.29 GiB, first-token p95 839 ms, complete p95 1389 ms). Release-grade
certification (cold-readiness and cancellation trials) remains open for
packaging; see `VISION_STATE.md` and
`docs/evidence/2026-09-19-user-v4-results.json` for preserved original results.

### One-shot assistant (M006)

```bash
PYTHONPATH=src python -m vision_assistant.assistant_cli shot.png --preview-only
PYTHONPATH=src python -m vision_assistant.assistant_cli shot.png
```

Previews and normalizes a screenshot you selected, asks one question with the
pinned Qwen3.5-4B configuration (context 4096, thinking off), prints
`[visible]`/`[inferred]`/`[unknown]` labels with real timings, writes a JSONL
trace under `runs/m006/`, and deletes the private artifact before exit.

`--evidence-ocr` (M007) adds optional local Vision OCR evidence: the image is
zoomed ×2 in-process, the extracted facts are appended to the model prompt,
and only counts and provenance kinds enter the trace.

Interrupting any stage (Ctrl+C) exits cleanly: one JSON line with the stage and
trace path, a `cancelled` trace record, the artifact purged, exit code 130, and
no orphaned server process. Retry is re-running with the same image; reset is
artifact release. Live evidence is preserved in
`docs/evidence/2026-09-19-m006-live-demo.md` and
`docs/evidence/2026-09-19-m006-stop-check.md`.

### Evidence augmentation measurement (M007)

```bash
PYTHONPATH=src python -m vision_assistant.augment_cli
PYTHONPATH=src python -m vision_assistant.augment_cli --heldout-all
```

Runs the frozen difficult subset (or the full held-out set) twice per case —
baseline question vs question plus local Vision OCR facts — scores both with
the frozen scorer, and writes a side-by-side JSON under `runs/m007/`.

Measured 2026-09-19 on the pinned model: held-out 23/24 → **24/24** with OCR
evidence (the only failure recovered, no regressions, unsupported 0,
forbidden 0).

### Multi-turn chat (M008)

```bash
PYTHONPATH=src python -m vision_assistant.assistant_cli shot.png --chat
PYTHONPATH=src python -m vision_assistant.assistant_cli shot.png --chat --evidence-ocr
```

Keeps one capture bound to one bounded session (12 turns, 4000-character
transcript budget, stale warning after 15 minutes); `:status`, `:reset`,
`:quit`; reset releases the artifact. Measured 2026-09-19: 6/6 frozen
reference/correction tasks passed, all artifacts released, prompts ≤ 333
characters.

### Local UI (M009)

```bash
PYTHONPATH=src python -m vision_assistant.ui_server --open
```

Serves a dependency-free page on **127.0.0.1 only**: pick a PNG, drag on the
preview to black out a region before sending, capture, then ask bounded
follow-ups. Stop shuts the model down and releases the capture; reset
releases between sessions; the server rejects foreign origins, caps request
sizes, and never logs request bodies.

All five read-only capstones passed live on 2026-09-19 — see
`docs/evidence/2026-09-19-m009-capstones.md`.

### Intent proposals (M010)

```bash
PYTHONPATH=src python -m vision_assistant.propose_cli
```

The model proposes actions as JSON intents; every proposal is parsed
strictly and reviewed by the consequence policy before any preview is shown.
No executor exists in this project — nothing can control the Mac. Measured
2026-09-19: 13/13 adversarial payloads contained, zero bypasses.

### Simulated action loop (M011)

```bash
PYTHONPATH=src python -m vision_assistant.sim_cli
```

Runs three frozen tasks against a deterministic toy app: the model proposes
schema-constrained intents, the loop validates, approves, fake-executes
(Python state only), and verifies against state predicates. Measured
2026-09-19: 3/3 tasks done in one step each, zero host input events.

### Read-only macOS grounding (M012)

```bash
PYTHONPATH=src python -m vision_assistant.grounding_cli --verify   # frozen gate, no permission
PYTHONPATH=src python -m vision_assistant.grounding_cli --check    # trust state (no prompt)
PYTHONPATH=src python -m vision_assistant.grounding_cli --request-permission   # explicit opt-in
PYTHONPATH=src python -m vision_assistant.grounding_cli --dump --app Calculator
PYTHONPATH=src python -m vision_assistant.grounding_cli --ground --app Calculator --target "7" --capture --ocr-check
```

Aligns a window's Accessibility elements with its screenshot and resolves
targets to stable identities — read-only, with the opt-in Accessibility
permission. Measured 2026-09-19: gate 44/44; "7"/"5"/"9" grounded at 2x with
OCR-matched crops; absent targets fail closed; zero input events.

### Supervised executor (M013)

```bash
(runs/m013-tools/practice_window >/dev/null 2>&1 &)   # disposable practice window
PYTHONPATH=src python -m vision_assistant.supervised_cli
```

The pinned model proposes; every action is previewed with a screen overlay,
confirmed interactively, re-checked for freshness, performed through the
single writer helper, and verified by re-observing the window. Measured
2026-09-20: 3/3 frozen tasks performed and verified, zero unapproved
actions; refusal paths all demonstrated with nothing posted.

### Bounded task agent (M014)

```bash
(runs/m013-tools/practice_window >/dev/null 2>&1 &)          # disposable practice window
PYTHONPATH=src python -m vision_assistant.agent_cli           # pinned model, stepwise
PYTHONPATH=src python -m vision_assistant.agent_eval          # 22-scenario deterministic gate
PYTHONPATH=src python -m vision_assistant.agent_eval --interrupts 10 --skip-scenarios
```

One frozen goal per task, pursued as separately confirmed steps under hard
budgets (`--max-steps`, `--max-seconds`, `--max-recoveries`); scripted
demos via repeatable `--step`. Measured 2026-09-20: three frozen goals
finished stepwise (zero unapproved); stale-frame recovery and
external-change takeover demonstrated live; unexpected dialog, permission
loss, budget exhaustion, injection-targeted, and off-goal proposals each
blocked safely; interruption p95 18.1 ms over ten real SIGINT samples.

### Packaging and offline verification (M015)

```bash
sh runs/m015/bundle-0.1.0/install.sh ~/vision-assistant      # offline installer (fresh venv)
~/vision-assistant/bin/vision doctor                          # environment + permission education
~/vision-assistant/bin/vision smoke                           # audit + model check + grounding 44/44
~/vision-assistant/bin/vision smoke --with-model              # + verified read-only ask (try with Wi-Fi off)
~/vision-assistant/bin/vision install --bundle <bundle> --prefix ~/vision-assistant   # upgrade
~/vision-assistant/bin/vision rollback --prefix ~/vision-assistant                     # switch back
~/vision-assistant/bin/vision uninstall --prefix ~/vision-assistant                    # dry run; --apply removes code
```

Measured 2026-09-20: bundle built from the pinned model directory and
verified (58 files, 504 KB); fresh-prefix install (venv on Python 3.14.7);
doctor education; smokes 44/44 with verified asks in 3.1–4.7 s; a
Seatbelt-sandboxed run denying all non-loopback networking reproduced the
read-only profile; upgrade/rollback kept both versions; uninstall removed
code and kept models unless explicitly asked.

### Evaluation and field manual (M016)

```bash
PYTHONPATH=src python -m vision_assistant.evaluation_cli trace        # waterfall for the canonical real turn
PYTHONPATH=src python -m vision_assistant.evaluation_cli failures     # the honest failure catalog
PYTHONPATH=src python -m vision_assistant.evaluation_cli commands     # exact reproduction commands
PYTHONPATH=src python -m vision_assistant.evaluation_cli teachback    # the five gate teach-back tasks
.venv/bin/python scripts/serve_learning_lab.py                        # the field manual at http://127.0.0.1:4173/
```

Measured 2026-09-20: canonical turn 1547.2 ms total (model stage 99.94%,
first token 723 ms); the field manual's waterfall, failure explorer
(12 entries with component chips), teach-back cards, copyable commands,
and the 5/5 quiz grader were verified in a live browser; the fixture
procedure ran as a worked example (freeze 121/121 PASS, then reverted).

### Hardening audit (M017)

```bash
PYTHONPATH=src python -m vision_assistant.audit_cli run        # 11 areas, 26 checks; exit 0 iff zero critical
PYTHONPATH=src python -m vision_assistant.audit_cli sign --bundle runs/m015/bundle-0.1.0
PYTHONPATH=src python -m vision_assistant.audit_cli support    # regenerate docs/SUPPORT.md
```

Measured 2026-09-20: 26/26 checks green with zero critical failures; two
bundle builds byte-identical; install→upgrade→rollback→uninstall
re-verified on real bundles; the release manifest is byte-stable. Unsigned
artifacts (no Apple notarization in this lab) are documented in
`docs/SUPPORT.md`.

## Planned browser-agent extension

[M018: computer-use agent](docs/COMPUTER_USE_AGENT_PLAN.md) adds a planned
screenshot-driven browser loop, 50 evaluation tasks, independent completion
checks, and a bounded Hacker News pilot. M018A (frozen task manifest, oracles,
and fixture/reset contracts) is complete and reproducible without a model:
`PYTHONPATH=src python -m vision_assistant.browser_cli verify`. M018B (disposable
browser helper + typed adapter) is complete and live-verified:
`PYTHONPATH=src python -m vision_assistant.browser_cli smoke`. M018C (the
screenshot-driven loop with the pinned model) is complete as a measured
smoke: 1/5 productive, failure classes on the record:
`PYTHONPATH=src python -m vision_assistant.browser_cli task --ids 01,11,21,41,31`.
M018D (frozen benchmark) is complete: **4/30 development and 3/18 held-out
productive**, refusals 1/2 expected-safe, zero forbidden actions — the
proposed gate is not met and is preserved as-is; the live Hacker News pilot
(M018E) was later executed once under a frozen scope — with the complete
front page visible the model clicked a non-navigating link twice and
produced no answer (failed run, recorded as-is). Evidence:
`docs/evidence/2026-09-20-m018d-benchmark.{md,json}`,
`docs/evidence/2026-09-20-m018e-live-pilot.md`.

M018T (target-assisted treatment) is measured: frozen plan → deterministic
implementation (113-test sweep) → smoke 3/5 → 4/5 after one recorded
revision → **paired fresh-set evaluation: 1/18 (screenshot) → 6/18
(target) productive on identical tasks** (Wilson 0.16–0.56; five genuine
flips), refusals 0/2 with one fixture-local submission attempt recorded,
zero forbidden actions. Tuning stopped at the freeze; both measured
boundaries stand as-is. Evidence: `docs/evidence/2026-09-20-m018t-eval.md`,
`docs/M018T_TARGET_ASSISTED_PLAN.md`, `docs/M018T_EVAL_FREEZE.md`.

M019 (task-typed treatment) is implemented through its frozen evaluation:
deterministic contracts (capability modes, `ui:` namespace, semantic form
operations with read-back, no-repeat enforcement, credential/submission
denial) → scripted integration gate PASSED (six scenarios, no model calls)
→ five-task development gate criteria met (4/5; the single documented prompt
revision `m019c-v2`) → frozen 20-task evaluation executed once: **10/18
productive** (answer 5/5, navigate 5/6, form 0/7 — correct actions refused
for extra fields), refusals 2/2 safe-blocked, **zero forbidden actions**,
no human rescue. The 15/18 gate was not met and the results stand as
measured. Evidence: `docs/evidence/2026-09-20-m019b-scripted.md`,
`docs/evidence/2026-09-20-m019c-dev.md`,
`docs/evidence/2026-09-20-m019d-eval.md`, `docs/M019_EVAL_FREEZE.md`.
