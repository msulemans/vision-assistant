# M018E — live Hacker News pilot (deferral lifted; frozen before its single run)

Status: the scoped change is recorded here and the pilot is **frozen before
its single run**, per the owner's 2026-09-20 instruction to continue to
completion. This lifts the M018D-era deferral explicitly and with evidence,
as that deferral itself required.

## Why the deferral is lifted (both original reasons changed)

The recorded deferral had two reasons: (1) the frozen navigation policy was
loopback-only, and enabling a live origin is a new scoped change requiring
its own evidencing — **this document is that record**; (2) the measured
screenshot-only capability made a one-shot pilot uninformative relative to
its risk — the target-assisted treatment has since measured **6/18
productive (paired +5 genuine flips)** on a fresh evaluation set, so a
transfer demonstration is now informative. The owner explicitly instructed
completion.

## The scoped change (exactly)

- `tools/browser_window.swift` gains an optional `--live-host <host>`
  argument. **Default absent = the frozen loopback-only policy is
  unchanged.** When set, the helper additionally allows `https://<host>`
  on port 443; every other origin is still cancelled and counted.
- `browser_session.BrowserSession` gains an optional `live_origins` tuple
  (default empty = unchanged). When set, `navigate` allows exactly those
  origins with strict boundary checks (`news.ycombinator.com.evil.example`
  can never match). Password typing, focus checks, stalled-frame rules,
  budgets, and stop semantics are unchanged.
- The fixture benchmark path never sets either option; the frozen 50-task
  manifest sha and every earlier result are untouched.

## The pilot task (frozen text)

- Site: Hacker News front page. One run, timestamped.
- Goal: "Read the front page of Hacker News from top to bottom. Find the
  first three stories whose main subject is AI or machine learning (models,
  research, products, or directly related policy; incidental keywords do not
  count). For each, report: its rank on the front page (1 = the top story),
  its title, its displayed points, and the domain shown next to the title.
  If fewer than three qualify, report that. Label uncertain items as
  uncertain. Then finish with the findings."
- Observation mode: target-assisted treatment, prompt `m018t-v2` (frozen).
- Budgets: the frozen limits (20 steps / 25 calls / 120 s). One run; no
  retries; no tuning afterwards.

## Safety assessment (recorded before the run)

- Read-only browsing with a non-persistent store: no account, no session,
  no cookies; no HN credentials exist on the machine.
- Navigation: HN origin only; external story links are cancelled by policy
  and counted; loopback remains allowed (unused).
- Typing: password fields are refused by the adapter; no login flow is part
  of the task. Worst case = the model wanders HN's read-only pages within
  the step budget; the run terminates at the budget at the latest.
- Reviewer protocol (openly specified): the reviewer compares the answer
  against its own snapshot of the HN front page fetched at ~run time (HN
  Firebase API read openly for review only — never substituting agent
  execution). Ranks drift on HN; ±1 rank and ±2 points are treated as
  matching, and the drift is recorded.

## Scoring (frozen)

- Claimed-set sanity: are the three stories the top-ranking AI/ML stories
  per the frozen definition (reviewer judgment on the top ~10 at run time;
  uncertain cases recorded)?
- Per claimed story: rank (drift-tolerant), title (normalized), points
  (drift-tolerant), domain (host match).
- Outcome classes: fully correct / partially correct (field-by-field) /
  incorrect / abstained (legal if fewer than three qualify) / failed run.
- Live HN success is a transfer demonstration, **not** part of the
  reproducible 50-task denominator.

## Attempt 1 (2026-09-20 12:00, recorded before the fix) — infrastructure failure

Attempt 1 loaded the live front page and ran three steps (146 targets
extracted, capped at 40) before the model server returned
`request (4109 tokens) exceeds the available context size (4096 tokens)`.
An earlier request had been truncated at 4095 tokens, which produced an
unparseable reply. The run aborted; the crash also killed the report write
(robustness gap). **This is a harness capacity defect, not a capability
measurement** — the frozen 4096 context was sized for fixture pages, and a
live front page with 40 long-labeled targets needs slightly more.

## Scoped harness fix (recorded before attempt 2; goal, prompt, model,
budgets, and scoring unchanged)

- Pilot context: **8192** (runtime capacity for real pages; CLI default for
  `hn-pilot`; the fixture benchmarks keep 4096 and are untouched).
- The pilot command is crash-safe: on any exception it writes a report with
  `outcome: failed:exception` and preserves screenshots.
- Attempt 2 is a single run under these settings; attempt 1's artifacts are
  kept as evidence (`runs/m018/m018e-hn-20260920-120002/server.log`).
