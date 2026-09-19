# M013 — supervised mouse and keyboard execution: live gate evidence

Date: 2026-09-20 (Australia/Sydney). Host: Apple M2 Max, macOS 27.0.
Commits: `7057ed3` (first build), `802f98c` (already_done + capture
robustness), `cab32b6` (accessibility value-write typing), `f454a4b`
(EOF-safe confirmer). Environment: workspace terminal on the user's machine
with the M012 Accessibility grant; disposable practice window
(`practice_window`, title "Practice App").

## The three-attempt arc (all attempts preserved)

| Attempt | Session | Outcome |
|---|---|---|
| 1 | `2026-09-20-m013-attempt1-model.json` | Window carried prior state; the model's two `finish` proposals were blocked (one after a black secondary-display capture); the notify click toggled an already-on checkbox and verification correctly failed. Fixes: `already_done` pre-check, observe-time values, black-capture fallback, authoritative element list. |
| 2 | `2026-09-20-m013-attempt2-model.json` | Window moved mid-run → `stale_frame` at preflight (zero side effects); typing refused `frontmost_mismatch` — probing showed macOS 14+ ignores cross-app activation. Fix: identity-bound accessibility value write for typing. |
| 3 (gate) | `2026-09-20-m013-supervised-run.json` | **All three frozen tasks done**: sync click (press), search type (`method: ax_value`), notifications click (press); each previewed, overlay shown, confirmed, re-checked, performed, verified. `performed_actions: 3`, `unapproved_actions: 0`. |

## Gate results (attempt 3)

| Task | Action | Verification |
|---|---|---|
| enable-sync | press `app:sync-toggle` | value 0 → 1 |
| type-search | type `app:search` = "hello" (`ax_value`) | contains "hello" |
| enable-notifications | press `app:notify-toggle` | value 0 → 1 |

Transcripts record per action: proposed payload, parsed intent, policy
verdict, grounded identity (role, name, identifier, frame), the exact
helper spec, preflight, preview, overlay shown, confirmation, recheck,
perform (method), and verified state — with observe-time values showing
each action's starting state.

## Refusal paths (each with zero side effects)

| Probe | Result | Evidence |
|---|---|---|
| Unknown element `app:ghost` | `not_found` | `2026-09-20-m013-probe-not-found.json` |
| Raw coordinates | `schema_rejected` | `2026-09-20-m013-probe-coordinates.json` |
| Secret target (Password) | `policy_denied` | `2026-09-20-m013-probe-secret.json` |
| Declined confirmation (`n`) | `approval_denied`, state unchanged | `2026-09-20-m013-probe-declined.json` |
| Window dragged mid-run | `stale_frame` (attempt 2) | `2026-09-20-m013-attempt2-model.json` |
| SIGINT at the confirmation prompt | `cancelled`, exit 130, nothing performed | `2026-09-20-m013-cancelled.json` |
| Repeat of a satisfied task | `already_done`, zero actions (×4 live) | `2026-09-20-m013-already-done.json` |

## Invariants observed

- `unapproved_actions: 0` in every session (the perform call is unreachable
  without a `True` confirmation; the counter is recorded per run).
- Exactly one artifact contains writer APIs (`ax_action.swift`); no mouse
  event APIs exist anywhere; the Python executor and runner contain none
  (source-scan tests).
- Secure elements are refused outright; secret-like targets are denied by
  policy before planning.
- Cross-app activation is impossible on modern macOS (verified by probe);
  the typing path was redesigned around that constraint rather than
  defeating it — typing writes the identified element's value and reads it
  back, so keystrokes can never land in another app.
- Window captures of a secondary-display window can come back black; the
  runner detects near-uniform darkness, substitutes a placeholder, and
  records `capture: black` — the element list is the authoritative source
  in the prompt either way.
