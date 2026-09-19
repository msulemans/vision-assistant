# M017 — public beta hardening: live gate evidence (and the end of the roadmap)

Date: 2026-09-20 (Australia/Sydney). Host: Apple M2 Max, macOS 27.0.
Commits: `8f577de` (first build; closure commit carries this file and the
docs sweep). Evidence: `docs/evidence/2026-09-20-m017-audit.json` (full
report) and `docs/evidence/2026-09-20-m017-RELEASE-0.1.0.json` (release
manifest).

## The audit gate

`PYTHONPATH=src python -m vision_assistant.audit_cli run` — **26 checks
across all eleven areas: 26 passed, 0 notes, 0 critical failures,
gate_pass=True** (first full run; re-verified after a fix, below).

| Area | What was observed |
|---|---|
| Capture privacy | runs/, captures/, models/ all git-ignored; 0700 dirs / 0600 files in the store; release-by-default with explicit retain |
| Trace redaction | **live canaries**: planted evidence text and pixel bytes never reach the trace; artifact released, zero leftovers |
| Malicious screen text | 22-scenario adversarial suite re-run green (unapproved 0); injection flagged, ignored on goal, blocked when targeted |
| Action policy | 13-payload funnel fully contained, 0 bypassed, budget denied; coordinates rejected by schema |
| Permission changes | mid-run loss → `blocked:permission_changed`; never-granted → `blocked:permission_required` |
| Supply chain | stdlib-only import scan clean; model files verified against the pin; runtime recorded (llama.cpp build 10621); licence manifest complete |
| Crash recovery | corrupt input fails typed with zero leftover artifacts; interrupt records a cancelled trace and purges |
| Accessibility | every input labeled (explicit, aria, or nested); every button named; skip link, aria-live, reduced motion present |
| Long-session resources | bounds frozen (12 turns, 4000-char prompt budget, 900 s stale warning); two sequential sessions leave zero artifacts |
| Reproducibility | **two bundle builds produced byte-identical content hashes** (62 files) |
| Release integrity | install 0.1.0 → upgrade 0.1.1 → rollback → uninstall (keeps models, removes code) re-verified on real bundles; release manifest byte-stable (63 files, aggregate `518d982ff8e2…`) |

## The audit tested itself

The audit's own teeth test caught a real bug on first contact: on Python
3.9 (no `sys.stdlib_module_names`), an **uninstalled** third-party import
resolved to `None` in the fallback scanner and was treated as stdlib.
Fixed the same day (unresolvable ⇒ flagged), 16/16 audit tests green,
gate re-run clean.

## Release artifacts

- Support matrix: `docs/SUPPORT.md` — interpreters (tested 3.9.6;
  verified 3.14.7), runtime build, permission table, feature matrix,
  profiles, known limitations, rollback/removal commands.
- Release manifest: `audit_cli sign` — SHA-256 over every bundle file plus
  a content aggregate; deterministic (no timestamps), with Apple
  signing/notarization explicitly documented as unavailable in this lab.
  Claimed integrity is exactly what is verifiable: content hashes.

## Roadmap complete

M001 through M017 are complete and evidenced. Every milestone's gate ran
against its frozen criteria; every failed run that found something real
stays in `docs/evidence/` and in the field manual's failure catalog.
