# M018B evidence — disposable browser helper and adapter (live smoke)

Date: 2026-09-20 (Australia/Sydney). Stage: M018B (browser adapter and
coordinate mapping). Model runs: 0.

## What was built

- `tools/browser_window.swift` — a disposable single-view WKWebView browser we
  own: fixed 1280×720 CSS viewport, non-persistent website data (no session,
  no profile), no tabs or downloads; navigation restricted to the configured
  loopback fixture port (refused and counted otherwise); JSON-lines protocol
  on stdin/stdout (`navigate`, `snapshot`, `click`, `type`, `key`, `scroll`,
  `back`, `state`, `quit`). Compiled clean with `swiftc -O`.
- `src/vision_assistant/browser_session.py` — the typed adapter: process
  lifecycle, JSON protocol with per-command timeouts, coordinate mapping
  (`map_screenshot_point`, pure), frozen guards (stale screenshot, origin
  escape, out-of-viewport, password/uncfocus typing refusals), budgets from
  `browser_tasks.LIMITS`, stop with quit → bounded wait → hard kill, and the
  temporary snapshot-directory lifecycle.
- `browser_cli.py smoke` — scripted live flow with optional screenshot-pixel
  click coordinates; writes a JSON report and keeps its snapshots.
- Tests: `test_browser_session.py` (12) + `test_m018_invariants.py` (8);
  the full affected sweep (session, invariants, tasks, fixture server,
  learning site, M013/M014/M015 invariants, packaging, audit) is 118 green.

## Safety posture (all enforced by tests)

- Input synthesis exists only in `browser_window.swift`, as in-app NSEvents
  sent to our own window's web view: no CGEvent anywhere, no OS-level event
  posting, no new permission, no other application can receive these events.
  The M013 "no mouse-event APIs" invariant holds unchanged; the new invariant
  tests freeze that `ax_action.swift` keeps only its sanctioned keyboard
  events and every other Swift file stays synthesis-free.
- A click is refused unless it references the most recent snapshot's
  sequence (adapter and helper both check).
- Typing is refused unless the page reports a focused editable, non-password
  element; password fields are refused before any key event exists.
- Navigation is refused outside the fixture origin/port in both layers; the
  helper counts every cancelled navigation.
- Budgets (20 steps / 120 s by default) are enforced before any command is
  sent; refusals never reach the helper.

## Live smoke results (report: `2026-09-20-m018b-browser-smoke.json`)

Sequence (twice, final run shown): launch → `navigate /news/` → snapshot
**2560×1440 at scale 2.0** → click at screenshot pixel (900, 445) → settle →
state shows `…/story/d03/` → post-click snapshot shows "Why database indexes
are still hard" with code **SC-dev-d03-de55** → `navigate /search/` →
snapshot → click (700, 240) on the query input → type "ai" → focused value
length **2** → clean stop: **0 orphan processes**, temporary snapshot
directory removed.

Two real findings surfaced by the live run and fixed the same day:

1. Synthesized clicks begin their navigation one runloop tick after the
   helper replies (first smoke raced the follow-up command and observed an
   `NSURLErrorCancelled` -999). The smoke now settles before re-observing;
   the loop stage will treat "click → observe again" as the contract.
2. Per-character key events coalesced in the text-input pipeline
   (typed 2 characters, only 1 landed). Typing now sends the whole string as
   one key event; the live check verifies 2/2 characters land.

## Reproduction

```
swiftc -O tools/browser_window.swift -o runs/m018-tools/browser_window
PYTHONPATH=src .venv/bin/python -m vision_assistant.browser_cli smoke --story-click 900 445 --type-click 700 240
PYTHONPATH=src .venv/bin/python -m unittest tests.test_browser_session tests.test_m018_invariants
```

## Interpretation and honest boundaries

The adapter — observe, click at screenshot coordinates, type, re-observe —
works end to end against the frozen fixture, with typed fail-closed guards
and clean process/file lifecycle. The *model* loop is not built yet: M018C
runs the five frozen smoke tasks (01, 11, 21, 31, 41) with the pinned model,
one initial run each, and inspects one failure class before any prompt change.
No task completion rate is claimed at this stage. The coordinates used above
were selected by the operator from the snapshots (the same interface the
model will consume); they are recorded so the runs are reproducible.
