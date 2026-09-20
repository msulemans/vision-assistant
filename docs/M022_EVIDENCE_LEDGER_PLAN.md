# M022 — multi-viewport evidence accumulation (scan mode): freeze record

Status: **Phase 1 harness FROZEN (2026-09-20). No model and no live site were
used.** The five-task development smoke is the next separately-approved step;
M021 stays preserved as the failed baseline whose measurement motivated this
treatment.

## Problem proven by M021

The correct stories were visible in the model's first screenshot; it read the
bottom screenshot accurately; it failed because earlier visual evidence
disappeared from context (one screenshot per call, no structured memory) and
its first scroll jumped straight to the page bottom. That is a
cross-viewport evidence problem — not yet proof the pinned 4B model is too
weak.

## Hypothesis

Trusted viewport traversal plus a structured evidence ledger will let the
same pinned 4B model combine facts across a long page. This is the last
harness improvement to try before a stronger model is justified.

## Frozen contract

### 1. Trusted page traversal (no model amounts)

- Begin at scroll position 0 (enforced; a mid-page start refuses).
- The model's advance action is `next_viewport` with **no amount**; trusted
  code moves **at most 70% of one viewport per step** (>=30% overlap), by
  DOM scroll (activation-independent).
- Continue top-to-bottom until the document end; **maximum 8 viewports**.
- Every viewport records `observation_id`, `scroll_y`, `viewport_height`,
  `document_height`.
- **Skipped ranges and repeated unchanged viewports are rejected** —
  fail-closed terminal `failed:traversal` with the reason
  (`viewport_unchanged`, `viewport_gap` > 70%+2px, `viewport_metrics_changed`,
  `viewport_layout_changed` when the document height shifts, `viewport_budget`).

### 2. Per-viewport extraction (the model's whole action set)

`record_candidates`, `no_candidates`, `next_viewport`, `finish_selection`,
`stop` — **nothing else exists**: clicking, typing, forms, submissions, and
navigation are not in the action set or the constrained-decoding schema.
Each candidate carries `rank`, `title`, optional `visible_points`,
`ai_relevance` (`primary`/`incidental`), `reason`, and **the observation_id
of the screenshot it was read from** (must be the CURRENT observation; stale
or unknown ids are refused).

Phases (all validator-enforced): **scanning** (not at the end) → **recording**
(the final viewport is still recorded *with its screenshot*; one more
`next_viewport` closes the traversal — no scroll happens) → **final** (a
ledger-only call, no screenshot: a 1×1 placeholder stands in for the
adapter's image argument). `finish_selection` is refused while traversal is
incomplete AND while the final viewport has not been recorded.

### 3. Trusted evidence ledger

Candidates are stored across observations; every field keeps its supporting
`observation_id`. **Duplicates (same rank + normalized title) and conflicts
(rank reuse with another title, title moving ranks) are rejected with
feedback and never overwrite.** Stale/unknown observations are rejected.
Screenshots are never embedded in logs or reports (paths only).

### 4. Completion and the trusted link mapping

- After the traversal closes, **trusted code sorts the ledger by rank and
  selects the first three candidates marked `primary`** (fewer if fewer
  primaries exist). The final model call receives only the bounded structured
  ledger; it may explain the selection but **cannot add, remove, or change
  stories** (the `ranks` it returns must equal the trusted selection
  exactly).
- `observed_at` is trusted harness metadata (UTC).
- **After the selection**, trusted code maps each exact visible story title
  to its HN item link from accepted DOM link rows (`item?id=...` only;
  same-row or the row directly below; ambiguities map to null). The link
  data **never enters any model prompt** and is labelled in the result:
  `hn_link_note = "hn_link is trusted browser metadata … never enters any
  model prompt"`.

### Example synthetic ledger (deterministic; produced by the module)

```json
[
 {"rank": 1, "title": "Exfiltrate Your Weights", "visible_points": 218,
  "ai_relevance": "primary", "reason": "LLM weight exfiltration tool",
  "observation_id": "obs-1"},
 {"rank": 8, "title": "AI generated posters don't have to be horrible",
  "visible_points": 1451, "ai_relevance": "primary", "reason": "AI image generation",
  "observation_id": "obs-1"},
 {"rank": 3, "title": "English: A vs. An", "visible_points": 134,
  "ai_relevance": "incidental", "reason": "language, not AI", "observation_id": "obs-1"},
 {"rank": 9, "title": "I built non-autoregressive decision models",
  "visible_points": 1146, "ai_relevance": "primary", "reason": "RL decision models",
  "observation_id": "obs-2"}
]
```

→ trusted selection: **ranks [1, 8, 9]** (incidental 3 excluded, order by
rank, evidence spanning two viewports).

## Budgets (frozen)

| Limit | Value |
| --- | --- |
| Viewports | 8 (trusted; the 9th advance attempt is refused with a hint) |
| Model calls | 20 |
| Wall clock | 180 s |
| Context | 8192 |
| Schema | exact `oneOf` branches, `additionalProperties:false`; smoke runs with `--require-schema` semantics (zero fallbacks permitted) |

## Deterministic verification record (no model, no browser, no network)

`tests/test_m022_scan.py` — **30 tests, all green**; focused sweep over the
scan module + all affected lanes + `test_m019_invariants`,
`test_m018_invariants`, `test_m015_invariants`, `test_package_cli`,
`test_learning_site`: **223 tests OK**.

| Required proof | Test |
| --- | --- |
| no skipped viewport ranges | `test_advance_rejects_unchanged_gap_and_layout_changes`, `test_skipped_range_fails_the_run_closed` |
| overlap between captures | `test_steps_are_at_most_70_percent_with_overlap` |
| cannot finish before document end | `test_finish_is_gated_on_completion_and_exact_selection`, `test_cannot_finish_before_the_document_end` |
| evidence survives later screenshots | `test_two_viewport_scan_records_evidence_and_finishes` (ledger keeps obs-1 and obs-2 entries) |
| stale observation rejected | `test_stale_or_unknown_observations_rejected`, `test_stale_and_duplicate_candidates_are_fed_back` |
| duplicate + conflicting candidates rejected | `test_duplicate_and_conflicting_claims_rejected_without_overwrite` |
| final answer cannot contain unrecorded candidates | `test_finish_is_gated_on_completion_and_exact_selection` (ranks must equal the trusted selection) |
| trusted ranking selects the lowest three qualifying ranks | `test_selection_is_the_lowest_three_primaries` |
| clicks/types/submissions unavailable | `test_interaction_actions_do_not_exist`, `test_schema_has_exactly_the_scan_actions`, `test_no_interaction_calls_and_link_data_never_in_prompts` |
| reviewer/API data never enters prompts | `test_reviewer_canary_file_never_reaches_prompts`, `test_no_interaction_calls_and_link_data_never_in_prompts` (link rows incl. a canary href appear in the result, never in a prompt) |
| budgets and crash-safe reporting | `test_call_budget_caps_the_run`, `test_viewport_budget_bounds_a_very_long_page`, `test_atomic_write_survives_a_crash`, `test_cmd_m022_reports_a_crash_before_any_model_call` |

Also verified, with the real helper on the local dev fixture (no model, no
network): `browser_cli m022-hn --scripted-check` — **PASS** (navigate +
capture, the new generic `links` command returned 19 DOM rows, traversal
begin validated at y=0, document-end detected for a single-viewport page,
zero orphans). The float `method:"dom"` scroll shares its JS branch with the
int path already proven live in the M021 run (`scroll_y 0 → 498`).

## The future smoke run (NOT executed; needs explicit go-ahead)

Five-task development smoke (the frozen next step): a fresh dev set of five
long-page scan tasks — **to be authored and frozen in a separate step** —
run once each with the pinned Qwen3.5-4B.

**Exact budget:** ≤ 5 tasks × (≤ 20 calls, ≤ 8 viewports, ≤ 180 s) = **≤ 100
model calls** plus one model load; one run per task; no retries; zero
fallbacks; abort criteria: any `failed:traversal`, any fallback, or fewer
than 4/5 structurally finished runs.

Minimal variant (live HN, single run) if the dev set is deferred:
`PYTHONPATH=src .venv/bin/python -m vision_assistant.browser_cli m022-hn`
— expected **5–8 calls** (record vp1, advance, record vp2, close, confirm),
hard cap 20.

Non-goals: no rerun of M021, no M021-set reuse, no larger model in this
phase, no answer-content tuning. If the 4B model cannot combine viewport
evidence even with this ledger, a stronger model is justified — with this
harness as the fair test.
