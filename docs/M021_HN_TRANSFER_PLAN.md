# M021 — read-only live Hacker News transfer (answer mode): freeze record

Status: **Phase 1 harness FROZEN (2026-09-20). The single live run is ready
but NOT executed** — it runs only after this freeze is committed, once, and
nothing auto-continues.

This is a separately labelled treatment of the M018E failure, not a retry:
M018E stays preserved as the old failed baseline (screenshot-only loop, the
model clicked useless targets because clicking was available). M021 uses the
M020 task-typed architecture in `answer` mode, where the only page-touching
actions are scroll and wait.

## Goal and classification rule (frozen before the run)

GOAL, sha256 `867b5b42e6669ce583920d207e8ba1477e93708899f27cd4293501c830835afc`
(pinned in `tests/test_m021_hn.py`):

> Open the Hacker News front page and report the first THREE stories whose
> main subject is AI or machine learning, in front-page rank order. Rank is
> the number shown at the start of a story's row (1 is the top story); the
> list continues below the visible area, so scroll down to read the rest. A
> story qualifies only when its main subject is AI/ML — an AI model, a
> research result, a product whose core purpose is AI/ML, or directly
> related policy or safety news. An incidental 'AI' word inside an otherwise
> unrelated story does not qualify, and generic software or business stories
> do not qualify. For each qualifying story report: rank, title (exactly as
> shown), url (the source domain shown after the title; for text posts use
> news.ycombinator.com), points (the visible number), and a short reason why
> the story is mainly about AI/ML. Set found to the number of qualifying
> stories you report: exactly three unless fewer than three qualify. Only
> report what you can see in a screenshot; if something is not visible, do
> not guess. When done, reply with finish_answer.

CLASSIFICATION_RULE (reviewer-side statement of the same semantics; used only
by the reviewer, never passed to the model — pinned by the canary test):

> A story qualifies as AI/ML only when its main subject is artificial
> intelligence or machine learning: an AI/ML model, a research result, a
> product or system whose core purpose is AI/ML, or directly related
> policy/safety news. Incidental keywords in an otherwise unrelated story,
> and generic software or business stories, do not qualify.

## Frozen contract

| Item | Frozen value |
| --- | --- |
| Mode | `answer` (M020 task-typed architecture) |
| Allowed actions | `scroll`, `wait`, `finish_answer`, `stop` |
| Structurally unavailable | `click`, `click_target`, typing (`fill_field`), `select_option`, `set_toggle`, `save_form`, `back`, `finish`, navigation (three layers: capability manifest, exact `oneOf` action-schema branches, origin policy) |
| Target lists | never requested or sent (`observe_targets=False`); the observation is screenshot + trusted scroll position + bounded history |
| Observation | one viewport screenshot per step; trusted `scrollY/scrollHeight/innerHeight` line (helper `state` reply, additive change, compiled clean); history bounded to the last results |
| Scroll delivery | in-page JS `scrollBy` (`method:"dom"` — activation-independent; the M019B lesson: synthesized key events can be swallowed in unattended runs). Opt-in per session; the frozen key-event path for every other caller is untouched |
| Context | 8192 |
| Budgets | max 4 scrolls, 8 model calls, 120 s (attempting a 5th scroll is refused with a hint; persistent attempts terminate) |
| Schema policy | `--require-schema` semantics hard-wired: a schema request failure is fatal; **zero fallbacks permitted** |
| Origin policy | helper `--live-host news.ycombinator.com` + session `live_origins` — HN only; no other origin can load |
| Model | pinned Qwen3.5-4B Q4_K_M + mmproj, thinking off (unchanged) |

The `finish_answer` branch of the schema carries an exact nested answer
object (M020 "exact shape" doctrine): `{stories: [{rank,title,url,points?,
reason}], found}`, `additionalProperties:false` at every level, mirroring the
validator (drift-pinned by tests). Contingency, recorded honestly: if the
pinned llama.cpp converter rejects this nested grammar, the first live call
fails closed (`failed:exception`, zero fallbacks); any simplification then
requires a NEW freeze — no silent downgrade.

## The answer: structural validation (runtime) and correctness (reviewer)

`validate_m021_answer` rejects, at proposal time with feedback and again at
execution: unknown/missing fields; `found` not an integer 0–3; `found !=
len(stories)`; non-object stories; missing/unexpected story fields; rank not
an integer ≥ 1; **duplicate ranks**; **ranks not strictly increasing**
(front-page rank order); duplicate urls (case-insensitive); empty strings,
over-long strings, control characters; **`ui:` references or `t<N>` target
ids anywhere**; non-integer or negative points.

`observed_at` is **trusted harness metadata** (UTC at model-session launch),
never produced by the model; the frozen result file is
`{stories, found, observed_at}` written by trusted code (`result.json`).

**Success gate (reviewer-scored after the run):** three reviewer-confirmed
top-3 AI/ML stories in rank order with correct visible titles and displayed
source domains, zero unsupported entries (everything traceable to the
captured screenshots), zero forbidden actions, zero fallbacks, zero orphan
processes, no human rescue. Only if the reviewer confirms, from the pre-run
capture, that fewer than three qualifying stories were visible: the stated
shorter set must be exactly all qualifying stories present. Points are
checked against the pre-run capture and (post-run) the HN API; slight drift
in points between run and API read is expected and noted, never averaged
away.

## Reviewer protocol (frozen)

1. **Before the model run**, trusted code captures the front page with its
   own helper (no model): `reviewer/snapshot-01..03.png` + `snapshot.json`
   (URL + UTC timestamp), covering the full list via page-down scrolls.
2. **After the agent run only**, the reviewer may consult the HN API or
   article pages, solely for scoring.
3. **Reviewer data never enters the model prompt** — the capture lives in
   `reviewer/`, is written before the model session starts, and is not read
   by any prompt-building code path (canary test: a planted reviewer file's
   content and the CLASSIFICATION_RULE text are absent from every prompt).

## Retention

Run screenshots are copied out of the ephemeral session dir to
`shots-kept/` before teardown and listed in `report.json`; reviewer captures
stay in `reviewer/`. Both live under `runs/m021/<run>/` (Git-ignored, the
normal policy for run artifacts) for independent review.

## Deterministic verification record (no model, no browser, no network)

26 tests in `tests/test_m021_hn.py`, all green; focused sweep including
`test_m020_schema`, `test_browser_typed`, `test_browser_agent`,
`test_browser_target_agent`, `test_browser_session`, `test_m019_invariants`,
`test_m018_invariants`, `test_m015_invariants`, `test_package_cli`:
**193 tests OK** (the audit caught a scheme-separator literal in the new
module's docstring — fixed before freeze; the frozen M015 audit passes
again).

| Required proof | Test |
| --- | --- |
| answer mode exposes no click/type/navigation | `test_manifest_excludes_every_interaction_action`, `test_action_schema_has_no_interaction_or_target_fields`, `test_validator_refuses_interaction_kinds_in_answer_mode` |
| target lists omitted | `test_run_never_requests_targets_and_omits_target_block` (fake session records any `targets()` call) |
| result schema validation | `AnswerValidationTest` (valid + 22 rejection cases incl. duplicates/order/target ids/count) |
| scroll and call budgets | `test_scroll_budget_refuses_fifth_scroll_then_recovers`, `test_persistent_scrolling_terminates_within_budgets`, `test_call_budget_caps_the_run` |
| duplicate and unsupported-answer rejection | `test_duplicate_rank_answer_refused_then_corrected`, `test_found_mismatch_refused_then_corrected`, `test_verifier_failure_marks_finish_unverified` |
| reviewer data cannot enter the prompt | `test_reviewer_canary_never_reaches_the_prompt` |
| origin limited to Hacker News | `test_session_origin_policy_is_hacker_news_only`, `test_helper_live_host_gate_is_pinned`, `test_origin_literal_is_assembled_from_parts` |
| crash-safe report writing | `test_atomic_write_survives_a_crash_and_leaves_no_litter`, `test_cmd_m021_reports_a_crash_before_any_model_call` |

Also verified: helper compiles clean with the additive scroll-position and
in-page-scroll changes; activation-independent scroll delivery is pinned
(`ScrollDeliveryTest`); the frozen spec constants (4 / 8 / 120 s / 8192 / 3)
and the goal sha256 are pinned; read-only runs never arm the no-change guard
on scrolls (`test_no_change_guard_never_fires_on_readonly_scrolls`).

## The frozen live run (ONE run; nothing auto-continues)

```
PYTHONPATH=src .venv/bin/python -m vision_assistant.browser_cli m021-hn
```

(Defaults frozen: `--pin-dir models/qwen3.5-4b`, `--ctx-size 8192`,
`--reviewer-pages 3`; output root `runs/m021/m021-hn-<stamp>/`.)

Estimated model calls: **≤ 8 hard cap, expected 2–4** (one call per reading
step; the front page usually needs 0–2 scrolls before all three stories are
visible). Wall clock: ~2–5 minutes including model load and the reviewer
capture.

Non-goals (frozen): no clicking, no typing, no navigation, no external
articles, no second run, no prompt changes after this freeze. If the run
produces a structurally valid answer, the reviewer scores it afterwards; if
it fails, the failure is recorded as-is — the honest next step after a
failure is a stronger model, not guard/prompt churn on this set.
