# SPDX-License-Identifier: Apache-2.0
#
# sugar.verifier: embedded verifier for Python.
#
# Since the canonical verifier is the Rust CLI, the Python embedded
# verifier delegates to it via subprocess. This keeps the Python kit
# lightweight while ensuring byte-for-byte protocol conformance.
#
# Usage:
#   from sugar.verifier import verify_project
#   report = verify_project("/path/to/project")
#   print(report.summary)

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class HandshakeReport:
    """Result of running the Sugar verifier on a project."""

    success: bool
    tier1_discharge_fraction: float
    tier2_discharge_fraction: float
    tier3_remaining: int
    violations: List[str]
    summary: str

    @staticmethod
    def from_json(data: dict) -> "HandshakeReport":
        return HandshakeReport(
            success=data.get("success", False),
            tier1_discharge_fraction=data.get("tier1_discharge_fraction", 0.0),
            tier2_discharge_fraction=data.get("tier2_discharge_fraction", 0.0),
            tier3_remaining=data.get("tier3_remaining", 0),
            violations=data.get("violations", []),
            summary=data.get("summary", ""),
        )


class VerifierNotFoundError(Exception):
    """Raised when the sugar CLI is not installed or not on PATH."""

    pass


# ---------------------------------------------------------------------------
# Verifier API
# ---------------------------------------------------------------------------


def find_sugar_cli() -> Optional[str]:
    """Locate the ``sugar`` binary on PATH."""
    return shutil.which("sugar")


def verify_project(
    project_root: str, extra_args: Optional[List[str]] = None
) -> HandshakeReport:
    """Run the Sugar verifier on a project directory.

    Delegates to the Rust ``sugar verify`` CLI. The project must have a
    ``.sugar/`` directory with a ``config.toml`` and any lifted contract
    files.
    """
    cli = find_sugar_cli()
    if cli is None:
        raise VerifierNotFoundError(
            "sugar CLI not found on PATH. Install it via: cargo install sugar"
        )

    cmd = [cli, "verify", project_root]
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    # The CLI outputs a JSON report on stdout in --json mode.
    # Default mode: parse structured output from stdout.
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            return HandshakeReport.from_json(data)
        except json.JSONDecodeError:
            return HandshakeReport(
                success=True,
                tier1_discharge_fraction=1.0,
                tier2_discharge_fraction=1.0,
                tier3_remaining=0,
                violations=[],
                summary=result.stdout.strip() or "verification passed",
            )

    # Failure: try to parse error output.
    return HandshakeReport(
        success=False,
        tier1_discharge_fraction=0.0,
        tier2_discharge_fraction=0.0,
        tier3_remaining=0,
        violations=[result.stderr.strip() or "verification failed"],
        summary=result.stderr.strip() or "verification failed",
    )


def prove_contract(
    contract_file: str,
    extra_args: Optional[List[str]] = None,
) -> HandshakeReport:
    """Run ``sugar prove`` on a single contract file.

    The contract file should contain JSON-serialized IR declarations.
    """
    cli = find_sugar_cli()
    if cli is None:
        raise VerifierNotFoundError("sugar CLI not found on PATH")

    cmd = [cli, "prove", contract_file]
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            return HandshakeReport.from_json(data)
        except json.JSONDecodeError:
            return HandshakeReport(
                success=True,
                tier1_discharge_fraction=1.0,
                tier2_discharge_fraction=1.0,
                tier3_remaining=0,
                violations=[],
                summary=result.stdout.strip() or "proof accepted",
            )

    return HandshakeReport(
        success=False,
        tier1_discharge_fraction=0.0,
        tier2_discharge_fraction=0.0,
        tier3_remaining=0,
        violations=[result.stderr.strip() or "proof failed"],
        summary=result.stderr.strip() or "proof failed",
    )
