# M012 — read-only macOS UI grounding: live gate evidence

Date: 2026-09-19 (Australia/Sydney). Host: Apple M2 Max, macOS 27.0.
Commits: `84108bc` (first build), `8094be3` (live-found fixes, frozen set
44 checks). Commands executed in the workspace terminal with the user's
explicit Accessibility grant for the host terminal app.

## Deterministic gate

`grounding_cli --verify` on the frozen synthetic states: **44/44 checks
pass** (11 tasks × 4 variants: two layouts × 1x/2x scales). Full result:
`docs/evidence/2026-09-19-m012-gate.json`.

## Permission flow (opt-in; both paths observed)

| Step | Observed |
|---|---|
| `--check` before grant | `accessibility trust: not granted` |
| `--dump` / `--ground` before grant | typed permission message, **exit 2**, nothing read |
| `--request-permission` (1st) | honest message; trust still not granted |
| `--request-permission` (2nd, after the user enabled the terminal in System Settings) | `accessibility trust: granted` |
| `--check` after grant | `accessibility trust: granted` |

## Live grounding (Calculator, 2026-09-19)

| Target | Status | Identity | Score | Region (px) | OCR cross-check |
|---|---|---|---|---|---|
| `7` | found | `AXButton '7' identifier=Seven path=w0/0/0/1/0/6` | 0.95 | (20, 374, 96, 96) | **matched '7'** |
| `5` | found | `AXButton '5' identifier=Five path=…/11` | 0.95 | (128, 482, 96, 96) | **matched '5'** |
| `9` | found | `AXButton '9' identifier=Nine path=…/8` | 0.95 | (236, 374, 96, 96) | **matched '9'** |
| `Delete` | found | `AXButton 'Delete' identifier=Delete` (earlier run) | 1.00 | (10, 133, 48, 48) | not re-run |
| `clear` | found | `AXButton 'All Clear' identifier=AllClear` | 0.85 | (128, 266, 96, 96) | read the visible key face; no token match — the AX name differs from the visible glyphs |
| `AC` | not_found | — | — | — | — |
| `card` | not_found | — | — | — | — |

Capture scale: Calculator on the built-in display → image 460×816 for a
230×408 pt window (**scales 2.000 × 2.000**); a VS Code window on a
negative-origin external display → 1920×998 at **1.000 × 1.000** with the
CG window id matched (`cg=10327`). OCR crops smaller than 96 px are zoomed
2× first (the M007 finding).

## Bug found and fixed during the live run

Resolving `AC` matched `Subtract` (score 0.80): the substring tier accepted
mid-word character sequences (`"ac"` inside `"subtract"`). Fix: substring
matches now require a word boundary and at least four characters; a frozen
regression task (`card` must not match `DISCARD`) was added, taking the gate
from 40 to 44 checks. Post-fix, `AC` and `card` both fail closed
(`not_found`, exit 1). The same run also motivated the `--app NAME` selector
(the frontmost app races with typing the next command in a terminal).

## Honest limitations recorded

- The AX name and the visible label can differ (`All Clear` vs the key face
  showing `AC`), so the OCR cross-check confirms identity only when they
  coincide; M013 candidate: treat visible-label OCR as an independent
  evidence source.
- Electron apps (VS Code) expose only a shallow read-only tree; their full
  tree appears only when a client requests enhancement — a write this
  milestone refuses.

## Zero input events

Enforced by construction and by the source-scan tests (the helper and every
M012 module contain no action APIs); observed live — no focus changes, no
clicks, no keys. All window access was read-only attribute reads plus
`screencapture -o -x -l` for the window image.
