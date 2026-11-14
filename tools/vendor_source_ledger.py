#!/usr/bin/env python3
"""Ad hoc wall-baseline runner (issue #3731 retry lane): run `sugar mint
--json` over a full installed vendor package and print the mint receipt
(the `.proof` written, its catalog CID and contract-set CID).

`sugar mint` is the one driver of a kit (step 1, #7806); this script no
longer drives `sugar lift --report`. The 2026-07-06 wall-baselines audit
pinned that path's `sourceLedger` output; those pins are history and are not
re-produced here.

Not wired into any test/gate; a one-shot measurement tool.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import sys

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
from sugar_repo_root import resolve_repo_root

sys.path.insert(
    0,
    str(
        resolve_repo_root()
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
    root = resolve_repo_root()

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
    proof_dir = output_dir / "proof"
    proof_dir.mkdir(parents=True)
    mint_result = subprocess.run(
        [
            sugar_bin,
            "mint",
            "--project",
            str(workspace),
            "--out",
            str(proof_dir),
            "--quiet",
            "--json",
        ],
        cwd=root,
        text=True,
        capture_output=True,
        env=env,
    )
    receipt_path = output_dir / "mint.json"
    if mint_result.returncode == 0:
        receipt_path.write_text(mint_result.stdout, encoding="utf-8")
    else:
        receipt_path.write_text(
            (mint_result.stdout or "")
            + ("\n" if mint_result.stdout and mint_result.stderr else "")
            + (mint_result.stderr or ""),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "package": package,
                    "failure": "mint-nonzero-exit",
                    "exitCode": mint_result.returncode,
                    "detail": (mint_result.stderr or mint_result.stdout)[:4000],
                    "receiptPath": str(receipt_path),
                }
            )
        )
        return 1

    try:
        receipt = json.loads(mint_result.stdout)
    except json.JSONDecodeError as exc:
        print(
            json.dumps(
                {
                    "package": package,
                    "failure": "mint-json-decode-error",
                    "detail": str(exc),
                    "receiptPath": str(receipt_path),
                }
            )
        )
        return 1

    print(
        json.dumps(
            {
                "package": package,
                "packagePath": str(package_path),
                "proofFile": receipt.get("proofFile"),
                "filenameCid": receipt.get("filenameCid"),
                "contractSetCid": receipt.get("contractSetCid"),
                "bytesWritten": receipt.get("bytesWritten"),
                "receiptPath": str(receipt_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
