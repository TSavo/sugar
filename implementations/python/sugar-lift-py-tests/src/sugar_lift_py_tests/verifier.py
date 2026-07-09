# SPDX-License-Identifier: MIT OR Apache-2.0
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
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .sugar_binary import SugarBinaryResolutionError, resolve_sugar_binary

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
    """Raised when the sugar CLI cannot be resolved through ``bin/sugarbin``."""

    pass


class VerifierProtocolError(RuntimeError):
    """Raised when the sugar CLI replies outside the verifier wire format."""

    def __init__(self, message: str, *, stdout: str, stderr: str) -> None:
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(message)


# ---------------------------------------------------------------------------
# Verifier API
# ---------------------------------------------------------------------------


def find_sugar_cli() -> Optional[str]:
    """Resolve the ``sugar`` binary through the repository hand-off entrypoint."""
    try:
        return str(resolve_sugar_binary())
    except SugarBinaryResolutionError:
        return None


def _raise_malformed_cli_json(action: str, stdout: str, stderr: str) -> None:
    context = stdout.strip() or "<empty stdout>"
    if len(context) > 500:
        context = context[:500] + "...<truncated>"
    raise VerifierProtocolError(
        f"{action} failed: malformed verifier JSON from sugar CLI "
        f"(verifier protocol drift); stdout={context!r}",
        stdout=stdout,
        stderr=stderr,
    )


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
            "sugar CLI could not be resolved through bin/sugarbin; "
            "set SUGAR_BIN or repair the repository binary hand-off"
        )

    # Resolve once so relative project roots (".", "myproj") stay correct when
    # we both cwd into the project and pass it as the CLI target.
    project = Path(project_root).resolve()
    cmd = [cli, "verify", str(project)]
    if extra_args:
        cmd.extend(extra_args)

    # ONE door: pin SUGAR_HOME to the project's staged .sugar.
    from .witness_harness import hermetic_sugar_env

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        env=hermetic_sugar_env(project),
        cwd=str(project),
    )

    # The CLI outputs a JSON report on stdout in --json mode.
    # Default mode: parse structured output from stdout.
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            return HandshakeReport.from_json(data)
        except json.JSONDecodeError:
            _raise_malformed_cli_json("verification", result.stdout, result.stderr)

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
        raise VerifierNotFoundError(
            "sugar CLI could not be resolved through bin/sugarbin"
        )

    # Prove a lone contract file: hermetic home is the contract's parent
    # project root if it carries .sugar, else the parent directory.
    contract_path = Path(contract_file).resolve()
    project = contract_path.parent
    if not (project / ".sugar").is_dir() and (project.parent / ".sugar").is_dir():
        project = project.parent
    cmd = [cli, "prove", str(contract_path)]
    if extra_args:
        cmd.extend(extra_args)
    from .witness_harness import hermetic_sugar_env

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        env=hermetic_sugar_env(project),
        cwd=str(project),
    )
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            return HandshakeReport.from_json(data)
        except json.JSONDecodeError:
            _raise_malformed_cli_json("proof", result.stdout, result.stderr)

    return HandshakeReport(
        success=False,
        tier1_discharge_fraction=0.0,
        tier2_discharge_fraction=0.0,
        tier3_remaining=0,
        violations=[result.stderr.strip() or "proof failed"],
        summary=result.stderr.strip() or "proof failed",
    )
