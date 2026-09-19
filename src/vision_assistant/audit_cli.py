"""M017 audit CLI: run the hardening suite, sign a release manifest, or
regenerate the support matrix.

    PYTHONPATH=src python -m vision_assistant.audit_cli run
    PYTHONPATH=src python -m vision_assistant.audit_cli sign --bundle runs/m015/bundle-0.1.0
    PYTHONPATH=src python -m vision_assistant.audit_cli support

`run` exits 0 iff zero critical findings; the JSON report lands under
runs/m017/ (git-ignored).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .audit import REPO_ROOT, release_manifest, run_audit, write_support

DEFAULT_REPORT_DIR = REPO_ROOT / "runs" / "m017"


def cmd_run(args: argparse.Namespace) -> int:
    report = run_audit()
    summary = report["summary"]
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for finding in report["findings"]:
            marker = {"pass": "PASS", "fail": "FAIL", "note": "NOTE"}[finding["status"]]
            print(f"  [{marker}] {finding['check_id']:<52s} {finding['detail']}")
        print(
            f"\naudit: {summary['passed']}/{summary['checks']} passed, "
            f"{summary['notes']} notes, {summary['critical_failures']} critical failures — "
            f"gate_pass={summary['gate_pass']}"
        )
    out = Path(args.out) if args.out else (DEFAULT_REPORT_DIR / f"{report['run_id']}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"report: {out}")
    return 0 if summary["gate_pass"] else 1


def cmd_sign(args: argparse.Namespace) -> int:
    bundle = Path(args.bundle)
    if not (bundle / "VERSION").is_file():
        print(json.dumps({"status": "failed", "reason": f"no VERSION in {bundle}"}))
        return 1
    manifest = release_manifest(bundle)
    out = Path(args.out) if args.out else (DEFAULT_REPORT_DIR / f"RELEASE-{manifest['version']}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "ok",
                "out": str(out),
                "version": manifest["version"],
                "files": len(manifest["files"]),
                "aggregate_sha256": manifest["aggregate_sha256"],
                "integrity": manifest["integrity"],
            },
            sort_keys=True,
        )
    )
    return 0


def cmd_support(args: argparse.Namespace) -> int:
    out = write_support(args.out)
    print(json.dumps({"status": "ok", "out": str(out)}, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vision_assistant.audit_cli",
        description="M017 public beta hardening: audit, release manifest, support matrix",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="execute the hardening audit suite")
    run.add_argument("--json", action="store_true")
    run.add_argument("--out", type=Path, default=None)
    run.set_defaults(func=cmd_run)

    sign = sub.add_parser("sign", help="write a reproducible release manifest for a bundle")
    sign.add_argument("--bundle", type=Path, required=True)
    sign.add_argument("--out", type=Path, default=None)
    sign.set_defaults(func=cmd_sign)

    support = sub.add_parser("support", help="regenerate docs/SUPPORT.md")
    support.add_argument("--out", type=Path, default=None)
    support.set_defaults(func=cmd_support)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
