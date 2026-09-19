# Support matrix — Vision Assistant (public beta)

Version 0.1.0 · Python ≥ 3.9 · stdlib only · macOS on Apple silicon (reference host: M2 Max).

## Interpreters

- **Tested:** CPython 3.9.6 (the project venv).
- **Verified:** CPython 3.14.7 ran the complete read-only smoke (M015).
- Not claimed beyond these: green elsewhere is likely but unverified.

## Runtime

- llama.cpp `llama-server` (installed separately, e.g. Homebrew); recorded build: 0.3.0 / build 10621 on the reference host.
- Xcode command line tools (`swiftc`) build the local helpers on first use.
- Model files are acquired explicitly and verified by size (fast) or full SHA-256.

## Permissions

- **Read a selected window or region** — macOS Screen Recording: asked by macOS only when you capture; nothing is captured in the background
  Revoke: System Settings > Privacy & Security > Screen Recording
- **Ground targets and read element state** — Accessibility: opt-in only: run `vision grounding --request-permission` yourself; nothing prompts on its own
  Revoke: System Settings > Privacy & Security > Accessibility
- **Perform supervised actions** — Accessibility: a separate, explicit opt-in; the read-only profile never posts actions
  Revoke: same Accessibility toggle; revoking stops actions immediately

## Feature matrix

| Capability | Default | Notes |
|---|---|---|
| Read-only ask / grounding / OCR | on | capture is explicit and least-scope |
| Loopback UI | on demand | binds 127.0.0.1 only, origin-allowlisted |
| Supervised actions (practice window) | **opt-in** | separate explicit grant; never real apps |
| Network | model acquisition only | installer, doctor, smoke, and runtimes are offline |

## Profiles

- **Inspect** (measured): ≤ 6 GiB warm target, ctx 4096
- **Balanced** (measured): ≤ 8 GiB warm target, ctx 4096
- **Quality** (planned, unpinned): ≤ 14 GiB warm target, ctx 4096

## Known limitations

- **Size verification cannot see same-size corruption** (M015): Byte counts are not integrity.
- **Electron apps expose a shallow accessibility tree** (M012): Electron exposes the full tree only after an accessibility-enhancement write, which this project refuses to perform.
- **Unsigned artifacts:** no Apple Developer ID or notarization in this lab; release integrity is SHA-256 content hashes (see `audit_cli sign`).
- The action executor targets the disposable practice window only.

## Rollback & removal

```bash
vision rollback --prefix PREFIX            # switch to the previous version
vision uninstall --prefix PREFIX           # dry run: shows the exact plan
vision uninstall --prefix PREFIX --apply   # removes code; models/captures kept
vision uninstall --prefix PREFIX --apply --remove-models   # explicit deletion
```

## Verifying this release

```bash
PYTHONPATH=src python -m vision_assistant.audit_cli run     # the hardening audit
PYTHONPATH=src python -m vision_assistant.package_cli verify --bundle BUNDLE
PYTHONPATH=src python -m vision_assistant.package_cli smoke
```
