#!/usr/bin/env python3
"""Ad hoc wall-baseline runner (issue #3731 retry lane): run `sugar lift
--report --json` over a full installed vendor package and print the
`sourceLedger` totals plus whether `lineAccounting` is present.

This exists because criterion14_conservation.py needs `lineAccounting`
(row-scoped, single-file schema from report_fmt::report_to_json), but the
directory/wall lift path (cmd_lift.rs:3069) emits `sourceLedger`/
`sourceAudits` only -- a distinct, coarser JSON shape with no
`lineAccounting` field. This script measures what the wall path actually
emits today so that gap is reported precisely instead of silently skipped.

Not wired into any test/gate; a one-shot measurement tool for the
2026-07-06 wall-baselines audit.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parents[1]
        / "implementations/python/sugar-lift-py-tests/src"
    ),
)

from sugar_lift_py_tests.idd.collect_panic_audit import (  # noqa: E402
    _prepare_audit_workspace,
    _resolve_installed_package_path,
)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: vendor_source_ledger.py <package> <output-dir>", file=sys.stderr)
        return 2
    package, output_dir = argv[0], Path(argv[1])
    root = Path(__file__).resolve().parents[1]

    sugar_bin = os.environ.get("SUGAR_BIN")
    if not sugar_bin:
        result = subprocess.run(
            [str(root / "bin/sugarbin"), "--profile", "release"],
            cwd=root,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            print(f"sugarbin resolve failed: {result.stderr}", file=sys.stderr)
            return result.returncode
        sugar_bin = result.stdout.strip()

    try:
        package_path = _resolve_installed_package_path(package)
    except RuntimeError as exc:
        print(
            json.dumps(
                {
                    "package": package,
                    "failure": "package-not-importable",
                    "detail": str(exc),
                }
            )
        )
        return 1

    if output_dir.exists():
        import shutil

        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    workspace = output_dir / "workspace" / package_path.name
    _prepare_audit_workspace(package_path, root, workspace, audit_only=False)

    env = os.environ.copy()
    lift_result = subprocess.run(
        [sugar_bin, "lift", "--report", "--json", str(workspace)],
        cwd=root,
        text=True,
        capture_output=True,
        env=env,
    )
    report_path = output_dir / "report.json"
    if lift_result.returncode == 0:
        report_path.write_text(lift_result.stdout, encoding="utf-8")
    else:
        report_path.write_text(
            (lift_result.stdout or "")
            + ("\n" if lift_result.stdout and lift_result.stderr else "")
            + (lift_result.stderr or ""),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "package": package,
                    "failure": "lift-nonzero-exit",
                    "exitCode": lift_result.returncode,
                    "detail": (lift_result.stderr or lift_result.stdout)[:4000],
                    "reportPath": str(report_path),
                }
            )
        )
        return 1

    try:
        report_json = json.loads(lift_result.stdout)
    except json.JSONDecodeError as exc:
        print(
            json.dumps(
                {
                    "package": package,
                    "failure": "lift-json-decode-error",
                    "detail": str(exc),
                    "reportPath": str(report_path),
                }
            )
        )
        return 1

    ledger = report_json.get("sourceLedger")
    has_line_accounting = "lineAccounting" in report_json
    print(
        json.dumps(
            {
                "package": package,
                "packagePath": str(package_path),
                "sourceLedger": ledger,
                "hasLineAccounting": has_line_accounting,
                "reportPath": str(report_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
