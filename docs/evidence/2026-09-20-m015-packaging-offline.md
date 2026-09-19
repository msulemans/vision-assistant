# M015 — profiles, packaging, and offline verification: live gate evidence

Date: 2026-09-20 (Australia/Sydney). Host: Apple M2 Max, macOS 27.0.
Commits: `e398dae` (first build), `67f8a4e` (wrapper routes `install`),
`0154191` (live-gate find: dispatcher consumed the subcommand + behavioral
wrapper tests). Install prefix: `~/vision-assistant`. Model: the pinned
Qwen3.5-4B directory from this repo, symlinked into the install.

## Build and dry run (before the gate)

- Bundle built from the pinned model directory: 58 files, 504 KB;
  `verify` clean — integrity hashes all match and the frozen offline audit
  finds zero violations (outbound HTTP clients only in
  `runtime_llamaserver.py`, loopback; URLs and `curl` only in the explicit
  `acquire.py`; no wildcard binds; installer/wrapper tokens network-free).
- Agent dry run: installed to a scratch prefix; `doctor` and both smokes
  green from the installed copy (44/44 grounding; verified ask, 4.7 s).
  This dry run caught the wrapper missing the `install` route → `67f8a4e`.

## Live gate (fresh prefix, fresh venv)

| Step | Result |
|---|---|
| `sh bundle/install.sh ~/vision-assistant` | ok — prefix created, venv built, code laid down, `bin/vision` wrapper installed |
| `bin/vision doctor` (first contact) | **bug found live**: the dispatcher consumed the subcommand, so `doctor` failed → fixed in `0154191` (passthrough routes keep `"$@"`; alias routes shift) with behavioral tests that execute the real dispatcher |
| `bin/vision doctor` (after fix) | environment (Python **3.14.7** in the fresh venv — newer than any tested interpreter; swiftc, llama-server build 10621, screencapture, accessibility granted), missing-models hint, install info, full three-capability permission education |
| `bin/vision smoke` | offline audit ok · models ok · grounding gate **44/44** |
| `bin/vision smoke --with-model` ×4 (one agent, three user) | model smoke ok=True, labels=2, released=True, 3.1–4.7 s; server log: `listening on http://127.0.0.1:8080` (loopback only) |
| **Sandboxed offline proof** | the same full smoke under a Seatbelt profile denying all networking except loopback: **all green** (3778 ms, released) — negative control in the same sandbox: `curl https://example.com` → exit 6, DNS denied |
| `build 0.1.1` → `bin/vision install` | upgrade 0.1.0 → 0.1.1, both versions listed, history records `upgrade` |
| `bin/vision rollback` | current back to 0.1.0, history records `rollback` |
| `bin/vision uninstall` (dry run) | plan: remove code (versions/current/bin/venv ≈ 1.5 MB), **keep models** |
| `bin/vision uninstall --apply` | removed code only; prefix retains `install.json`, `models` (symlink target untouched — the repo's 3.4 GiB never at risk), `runs` |

## Decisions recorded honestly

- The manual Wi-Fi-off variant remains on the checklist, but the offline
  claim is now enforced reproducibly without touching the user's network:
  a process-level sandbox that denies every non-loopback route while the
  read-only profile runs green inside it.
- The user was away for the closing choice; the conservative autonomous
  decision was to **keep the models** (never delete destructively without
  an explicit instruction). The `--remove-models` path is unit-tested and
  was shown in the dry-run semantics; the live deletion remains the user's
  explicit call.
- `_dir_size` reports 0 bytes for symlinked model directories (os.walk
  does not follow symlinks); deletion removes the symlink, never the
  target — noted so the 0-byte figure is not misread.
- "Clean Mac" is reproduced in-lab as a fresh prefix + fresh venv with no
  repository dependency; `README-INSTALL.md` and the manifest list the host
  prerequisites (Xcode CLT for swiftc, a llama.cpp runtime, Python ≥ 3.9,
  one-time model acquisition while online).

## Findings worth keeping

1. **The live gate caught a real dispatcher bug on first contact** — the
   argument-handling fix is now locked by behavioral tests that execute the
   installed wrapper for real.
2. **Python 3.14.7 ran the entire read-only path** (fresh venv from the
   machine's PATH): a useful portability data point above the tested 3.9.6.
3. **Size-mode model verification cannot see same-size corruption by
   design**; `--full-hash` exists for certainty, and `to-pin` hashes are
   reported as unverified rather than silently trusted.

## Evidence index (`docs/evidence/`)

`2026-09-20-m015-live-smoke-with-model-first.json` (agent run),
`2026-09-20-m015-live-smoke-{1,2,3}.json` (user runs),
`2026-09-20-m015-sandboxed-offline.json` (Seatbelt-denied networking).
Bundle: `runs/m015/bundle-0.1.0` (rebuilt with the dispatcher fix),
`runs/m015/bundle-0.1.1`.
