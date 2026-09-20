# Reciprocal learning curriculum

The goal is not merely to run a vision model. You should be able to explain the
pipeline, predict a failure, measure it, and teach someone else how the evidence
was produced.

Use this written path together with the dependency-free interactive field
manual at `learning/index.html` (or run
`python3.11 scripts/serve_learning_lab.py`). The site is updated from the same
canonical evidence and must never present a planned or simulated capability as
real.

## The loop

1. **Question** — state one falsifiable milestone question.
2. **Mental model** — draw pixels, text, control, and trust boundaries.
3. **Prediction** — write the expected result and likely failure.
4. **Small build** — change only the current milestone.
5. **Evidence** — deterministic check first, labelled real-local check second.
6. **Explain back** — describe what happened in simple words.
7. **Transfer** — change one condition and predict the new outcome.
8. **Record** — update `VISION_STATE.md`, including failures.

## Learning path

| Milestones | Concepts to teach | Practical proof |
|---|---|---|
| 001–003 | pixels/points, capture scope, image lifecycle, events, cancellation | trace a fake and user-approved capture |
| 004–006 | frozen evaluation, OCR, VLM image encoding, decoding, quantization, hallucination | compare models and explain one grounded answer |
| 007–009 | crops, OCR/accessibility provenance, visual memory, UI observability | diagnose a difficult screen without hidden retention |
| 010–012 | typed actions, policy, approvals, element grounding, stale observations | defeat unsafe proposals in a fake loop |
| 013–014 | supervised input, verification, recovery, stop controls | complete a disposable task with zero unintended actions |
| 015–017 | profiles, packaging, supply chain, privacy audit, teaching | reproduce and explain a clean offline install |

## Current lesson — Milestone 003

### A file path is not an image contract

Before a model sees an image, trusted code must prove that the container is the
format it claims to be, dimensions are bounded, checksums are valid, decoded
size cannot explode, and hidden metadata is removed. Milestone 003 accepts only
PNG so those guarantees remain understandable and dependency-free.

### Ephemeral means a tested lifecycle

"We do not save screenshots" is not a policy until a test proves the private
artifact exists only while needed and is deleted afterward. Retention is a
separate explicit option, never an accidental side effect.

The CLI must release its artifact even when writing the capture summary fails
(for example, a closed output pipe). A `finally` block preserves that cleanup
path, while `--retain` remains explicit. A valid PNG chunk checksum also does
not prove the compressed pixels are valid: decompression errors must become
the same recoverable `invalid_image` result as other image validation failures.

### Cancel, deny, and timeout are different

Escape means the user cancelled. Missing Screen Recording permission means the
platform denied capture. Waiting past the selection budget means timeout. The
first live attempt exposed that timeout and cancel were incorrectly merged;
the failure was preserved and the outcomes are now distinct.

### Pixels are not understanding

A screenshot is an array of pixels. A vision encoder turns regions into model
representations; a language model then predicts text. Neither step guarantees
that small terminal text was read correctly or that a diagnosis is supported.

### Visible evidence is not inference

"PostgreSQL connection refused on localhost:5432" may be visible. "The database
service is stopped" is an inference: common and useful, but not directly shown.
The assistant should label that difference and suggest a verification step.

### Local is a data boundary

Local means pixels, extracted text, prompts, model weights, answers, and traces
remain under local control. Running a local model while silently retaining every
screenshot would still violate the privacy goal.

### A model proposal is not permission

Seeing a button, deciding it is relevant, being allowed to click it, and
successfully clicking it are four different responsibilities. Trusted code and
the user own the last two.

## Teach-back prompts

- Why do we build a fake visual turn before downloading a model?
- Which part sees raw pixels, and how long are they retained?
- What is the difference between OCR accuracy and root-cause accuracy?
- Why can a fast token rate still produce a slow answer?
- Why is a coordinate click riskier than an Accessibility element click?
- What evidence would justify moving from a 4B model to a 9B model?
- What should happen when the screenshot does not show the cause?

## Milestone 003 explain-back

In simple words: an image is copied into a private temporary room, checked for
size and damage, cleaned of hidden notes, measured, and then removed. The same
room is used whether the image came from a file or the Mac selector. We still
need one deliberate live selection before calling this lesson complete.

## How the revised plan reaches a useful product

M006 is the first usable single-image assistant; M009 completes the read-only
workflow. Desktop actions are optional. Packaging does not depend on teaching
the computer to click. The learning site and evaluation evidence grow at every
milestone; M016 consolidates them rather than postponing them.

M004 separates development cases (used to improve a prompt) from held-out cases
(used to judge the frozen result). Repeatedly tuning against the held-out set
turns it into development data. Hand-authored correct, wrong, and abstaining
answers first prove the scorer works. The numerical targets in `METRICS.md`
are starting proposals to freeze before model output, not measured results.

M005 tests a small number of complete model/runtime configurations in sequence.
A difficult tiny-text case may expose an image-resolution problem rather than
a need for a larger model. Diagnose on development cases, then version and rerun
any changed evaluation. A fake clock cannot measure real latency, and a model's
“visible” label cannot prove its claim true. Real inference needs real timing,
private metrics, cancellation, and cleanup on every terminal path.

Teach back: Why are three successful demos insufficient to estimate p95?
What evidence would distinguish a decoder failure from insufficient image detail?
Why should the read-only product be valuable even if actions are never added?

## M005 lesson — a failed verdict can be a harness defect

The v4 contract allowed 23/24, but the harness still required 24/24. Correcting
that mismatch changes the aggregate quality verdict without hiding the one
failed UI-string case. Quality passing also does not mean evidence is complete:
missing cold-readiness or acquisition measurements must remain pending, not
silently count as passing. The original user-reported results are preserved.

Teach back: How would you test 23/24 versus 22/24 while ensuring forbidden
claims still fail? Why is a 24-case run insufficient proof of 48 warm trials?

## M005 outcome — selected configuration

Qwen3.5-4B (Q4_K_M, llama.cpp, thinking off, context 4096) is the selected
Phase-1 configuration: 23/24 on the frozen v4 held-out (0.95 pass-rate gate),
all safety metrics perfect, RSS 3.792 GiB, swap 0, acquisition 6.29 GiB.
Cold-readiness and cancellation certification trials remain open for
packaging. The next milestone was M006 — one-shot local Vision Assistant
(complete; see below).

## M006 outcome — the one-shot assistant

`assistant_cli` previews (normalize, hash, report), then asks one question and
prints a labelled answer with real timings; the JSONL trace records
preview/model_started/answer/done, and the private artifact is deleted on exit
(retain is explicit). Live demo: first token 651–659 ms, complete
1130–1145 ms, quotes verbatim, unknowns honest, artifact released. The stop
check ran twice (Ctrl+C during model load): clean cancel — one JSON line,
`cancelled` trace, artifact purged, exit 130, no orphaned server. That check
found and fixed a real bug: a startup interrupt used to crash with a traceback
and leak the artifact; regression tests now protect every stage. Next
milestone was M007 — evidence augmentation (complete; see below).

## M007 outcome — evidence augmentation closes the last failure

Augmentation was frozen before output was inspected: the difficult subset was
`m004-dialog-14` (the only held-out failure) plus `m004-small_text-13..15` as
an exact-text guard. Local OCR (macOS Vision, compiled from
`tools/vision_ocr.swift`; no package, no permission) misread the block-font
title at 1× ("UNSEVED BEFOBT"); zooming ×2 first (pure-stdlib `pixels.py`)
read `UNSAVED REPORT` at confidence 1.0 — ×4 regressed. Measured on the
pinned model: baseline reproduced v4 exactly (23/24, ui 0.9583) and
OCR-augmented prompts scored 24/24 — flipping the last failure — with
unsupported 0, forbidden 0, no guard regressions, and 1.25–1.49 s per
augmented call. Facts enter the model prompt only; traces record counts and
kinds, never text. Next milestone was M008 — multi-turn conversation
(complete; see below).

## M008 outcome — bounded multi-turn conversation

One session binds one capture (identity = trace id + content sha256); a new
capture never inherits history. Hard bounds: 12 turns, 4000-character
transcript budget (oldest dropped first, marked when omitted), 15-minute stale
warning; reset releases the artifact and closes the session; asking after
reset and exceeding the limit are typed errors. Measured on the pinned model:
6/6 frozen tasks passed — three reference questions (the follow-up must carry
a fact from the earlier turn) and three corrections (a false premise must be
contradicted with the true value) — every artifact released and prompts
bounded (max 333 characters). Follow-ups answered in 1.1–1.6 s. Next
milestone was M009 — usable capture and answer UI (complete; see below).

## M009 outcome — the usable local UI

A loopback-only stdlib server owns the trusted side and serves a
dependency-free page: pick a PNG, drag to redact a region before sending,
ask, and keep bounded follow-ups on one capture; stop shuts the model down
and releases everything; reset releases between sessions; failures appear as
typed banners with recovery hints. All five frozen read-only capstones passed
live on the pinned model (one-shot on real screenshots; reference and
correction follow-ups ~1.3 s; stop with no orphaned process; corrupt-file
recovery; empty artifact root after the privacy cycle). Two real bugs found
by the run were fixed: large captures overflowed the model context (a bounded
model view now downscales above 3M pixels for the model call only) and stop
during model load now aborts promptly. Next milestone was M010 — typed action
intents and policy (complete; see below).

## M010 outcome — typed proposals, zero execution

Seven intent kinds have a strict schema: unknown fields, raw coordinates,
oversized text, control characters, modifier-combo keys, and scroll abuse are
rejected at parse time. A consequence policy classifies every valid intent as
preview-only (observe/cancel/finish), needs-confirmation (all mutating
intents), or denied (secret-entry targets, window-scope escapes, budget
overruns). A frozen adversarial set — now 21 tests — cannot bypass any of it,
and a source-scanning test proves there is no executor anywhere. Live demo:
13/13 adversarial payloads contained with zero bypasses. The 4B model itself
proposed no parseable JSON yet — it quoted screen text and invented element
ids; the funnel is fail-closed, so nothing happened. Format scaffolding for
model proposals is noted for M011. Next milestone was M011 — disposable
simulated action loop (complete; see below).

## M011 outcome — the loop works, and the model had to be constrained

A deterministic practice app (a Python state machine rendered to a PNG) is
acted on by a simulated loop: observe → propose → validate → approve →
fake-execute → verify, with 12-step and 2-retry budgets and final states for
denial, approval refusal, stale observations, cancellation, and emergency
stop. The first live attempt blocked all tasks with `no_proposal`: the model
would not emit JSON even after a repair prompt — fail-closed worked, nothing
executed. The fix was to constrain the decoding itself: the runtime now
accepts a JSON schema (`response_format.json_schema`, converted to a
llama.cpp grammar) and the proposer uses it with a prompt-only fallback. The
second run finished all three frozen tasks in one step each, verified
against state predicates, with zero host input events. Lesson: format
compliance is an infrastructure problem, not a politeness problem. Next
milestone: M012 — read-only macOS UI grounding (no posted input).

## M012 outcome — read-only grounding, and a false positive the live run found

milestone: M012 — read-only macOS UI grounding (no posted input). Complete 2026-09-19.

The window's Accessibility tree and its screenshot are aligned through one
derived scale (image pixels / window points), so Retina and external
displays both work: a 2x capture on the built-in display and a 1x capture
on a negative-origin external display both aligned correctly, with the CG
window id matched. Targets resolve through normalized role-aware scoring —
exact names, token subsets, and boundary substrings — with stable
identifiers beating duplicate labels, and absence or ties failing closed
(`not_found` / `ambiguous`, never a guess). The live run earned its keep:
resolving "AC" on Calculator matched "Subtract" because the substring tier
accepted mid-word sequences; the fix (require a word boundary and at least
four characters) is frozen as a regression task, taking the gate to 44
checks. The permission story is honest both ways — nothing is read before
an explicit opt-in, the denial path is a typed message and exit 2, and
secure text-field values never leave the parser. Next milestone: M013 —
supervised mouse and keyboard execution (first executor; still disposable
targets, previews, confirmations, and stop).

## M013 outcome — the first host actions, and what macOS refuses to let you do

milestone: M013 — supervised mouse and keyboard execution. Complete 2026-09-20.

The executor turned anchors into actions: a click is an AXPress on an
element found by stable identifier (never coordinates), typing writes the
identified field's value through the accessibility API and reads it back,
and key events post only when the target app is frontmost. Everything runs
through one path — observe, propose, policy, plan, preflight, visible
overlay, explicit confirmation, freshness re-check, perform,
re-observation, verify — and anything doubtful refuses with nothing
posted. Live runs found three real things: prior state makes blind toggles
unsafe (fixed with an `already_done` pre-check), a black window capture
must not confuse the model (the element list is authoritative; blank
captures are detected and substituted), and macOS 14+ no longer allows one
app to activate another, so a synthetic keystroke path could never be
aimed safely — it was rejected live (`frontmost_mismatch`, nothing typed)
in favour of the identity-bound value write. Next milestone: M014 —
recovery and bounded task agent.

## M014 outcome — the agent that knows when to stop

milestone: M014 — recovery and bounded task agent. Complete 2026-09-20.

The executor became an agent: one frozen goal per task, pursued as a
sequence of separately proposed, previewed, confirmed, re-checked,
performed, and verified steps — each step re-derived from a fresh
observation, never executed blind from an up-front plan. Hard budgets
(8 steps, 120 seconds, 2 recoveries) make exhaustion a typed terminal
state, not a silent loop. The live gate showed every stop being honest: a
window moved mid-confirmation recovered by re-planning at the new position
and asking again; an unexpected modal dialog, a revoked permission, an
exhausted budget, an injection-targeted proposal, and an off-goal proposal
each ended in their typed blocked states with zero actions; an external
change to the screen was read as user takeover — the agent completed its
own approved action and then yielded, never fighting for focus.
Adversarial screen text was flagged and ignored: the screen is data, never
instructions. Interruption (SIGINT at the confirmation prompt) stopped the
agent with p95 18.1 ms across ten real samples. Next milestone: M015 —
profiles, packaging, and offline verification.

## M015 outcome — making it installable, and proving it offline

milestone: M015 — profiles, packaging, and offline verification. Complete 2026-09-20.

The lab became a product: a versioned bundle (source, tool sources,
artifact/licence manifest, integrity hashes, generated installer) installs
into a fresh prefix with its own venv; `doctor` explains every permission
on first run and never prompts; `smoke` replays the read-only profile —
the frozen 44-check grounding gate plus, with the model present, one
verified one-shot ask — from the installed copy. The offline claim is
enforced at three levels: a frozen source audit (outbound clients only in
the explicit model downloader; URLs and curl only there; the installer and
doctor touch no network at all), a loopback-only local server, and a
sandboxed reproduction run with every non-loopback network route denied
(negative control: DNS denied). The live gate caught a real dispatcher bug
on first contact (a consumed subcommand), fixed with behavioral tests that
execute the installed wrapper; a fresh venv on Python 3.14.7 ran the whole
read-only path. Upgrade keeps the previous version and rollback restores
it; uninstall removes code while models and captures survive unless the
user explicitly asks. Next milestone: M016 — evaluation and reciprocal
learning field manual.

## M016 outcome — the measurement becomes teachable

milestone: M016 — evaluation and reciprocal learning field manual. Complete 2026-09-20.

The lab now measures itself and teaches it back. One real recorded turn
runs through a latency waterfall that makes the honest point unmistakable:
99.94% of the time is the model, and everything else is measurement you
can trust. Twelve failures from the project's own history — including two
limitations that remain open — are browsable with components, causes,
fixes, and evidence links; the losing model run stays beside the
selection. Five teach-back tasks map one-to-one to the gate, each with a
checklist; the quiz now tests the network surface and stale-frame
recovery. The fixture-adding procedure was demonstrated end-to-end
(freeze → verify 121/121 → revert). The human learner walkthrough is
recorded as a standing item; the answer key and the worked example show
the expected depth. Next milestone: M017 — public beta hardening.

## M017 outcome — hardening, and the end of the roadmap

milestone: M017 — public beta hardening. Complete 2026-09-20.

The final milestone turned the product on itself: an eleven-area audit —
capture privacy, trace redaction (proven with planted canaries),
adversarial screen text, action policy, permission changes, supply chain,
crash recovery, accessibility, long-session bounds, reproducibility, and
release integrity — ran 26 checks to a clean gate and re-verified the
rollback/removal story on real bundles. Two bundle builds produced
byte-identical hashes; the release manifest is byte-stable; unsigned
artifacts are documented, never claimed. The audit even tested itself: its
teeth test caught a Python 3.9 fallback bug in the stdlib-only import
scanner, fixed the same day.

## Course complete — what this lab actually taught

Seventeen milestones from a contract and an empty repo to a hardened,
offline, locally-installed system that can see a screen, explain it,
propose actions, and — under supervision, budgets, and typed refusals —
take them in a disposable window. The through-line was never the model; it
was the discipline around it: freeze the gate before the build, keep every
failed run as evidence, let live runs find the real bugs (mid-word
substring matches, black captures, cross-app activation bans, dispatcher
argv, a 3.9 fallback), and let constraints redesign the system instead of
being defeated. Every claim in this curriculum traces to a command whose
observed result is recorded. That is the whole curriculum.

## Planned M018 — from practice window to browser tasks

Read [the computer-use plan](../docs/COMPUTER_USE_AGENT_PLAN.md). Learn why
a model's finish message is not a success oracle, why screenshot-only and
DOM-assisted observations need separate results, and why correct refusals
must not inflate productive completion rate. The 50 tasks and M018A–E gates
are proposals; no browser-agent benchmark result is claimed. M018A itself is
complete: the frozen manifest and its oracles are checked by
`python -m vision_assistant.browser_cli verify` (correct states pass, wrong
states fail, no model involved). M018B is complete too: a disposable browser
helper clicks and types at screenshot coordinates with typed refusals for
stale frames, origin escapes, and password fields — demonstrated live against
the frozen fixture. M018C adds the measured honesty: the pinned 4B model
managed 1/5 smoke tasks (only the already-satisfied one); it types without
clicking first, clicks the same spot twice, and answers before gathering
evidence — all recorded, none tuned away. M018D finished the story: three
recorded prompt iterations improved behaviour (clicking began; one dev task
passed after a rank-semantics fix), then the frozen benchmark ran once —
**4/30 development and 3/18 held-out productive**, zero forbidden actions,
gate missed and preserved, and the live Hacker News pilot was later run
once under a frozen protocol — the model had the complete front page in one
screenshot and produced no answer (failed run, recorded as-is). The lesson: build the instruments first, measure at the end, and
let the boundary be the result — a 4B vision model cannot yet drive
screenshot-only browsing reliably, and now there is evidence saying so.

The follow-up treatment is measured too. M018T kept the screenshot but gave
the model a bounded list of visible targets (opaque ids, visible labels,
clipped boxes) and let trusted code resolve clicks by id — a plan frozen
before any code, implemented with a deterministic test sweep, smoke-tested
at 3/5 → 4/5 across one recorded revision, then evaluated once on a fresh
20-task instance with a paired screenshot baseline. Result: **1/18 → 6/18
productive on identical tasks** (Wilson 0.163–0.563), with the honest
negatives recorded as well — the type-before-focus limit persisted, three
answer tasks lost their story code to a target-id confusion, and one
required-refusal run recorded a fixture-local submission attempt. The
instruments measured a boundary twice and both numbers are the result.

The typed treatment then tested one more hypothesis: trusted task typing
instead of free-form browsing. M019 froze capability modes the model cannot
escape — answer (no clicking), navigate (no typing), form (declared fields
and one authorized local save), stop — plus a `ui:` namespace so control
references can never be mistaken for page data, semantic fill/select/toggle
with read-back, no-repeat enforcement, and structural credential/submission
denial. The deterministic layers passed without a model (a scripted gate
covering six scenarios), the five-task development gate met its criteria at
4/5 after the one permitted prompt revision, and the frozen 20-task
evaluation ran exactly once: **10/18 productive** — answer 5/5, navigation
5/6, and **form 0/7**, where the model kept composing semantically correct
actions polluted with extra fields that the strict validator refused; both
refusals safe-blocked with zero side effects. The 15/18 gate was not met
and the numbers stand as measured — every failure closed structurally, which
is its own finding: the remaining wall is exact action-shape emission, not
safety.
