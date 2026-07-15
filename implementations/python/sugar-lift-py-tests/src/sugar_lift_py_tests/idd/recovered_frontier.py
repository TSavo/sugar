from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from .command_result import CommandResult

RunCommand = Callable[[list[str], Path, dict[str, str]], CommandResult]

_CENSUS_FIELDS = (
    "sourceFilesEnumerated",
    "sourceBodiesDemanded",
    "auditLeavesCompleted",
)


def _validate_terminal_vectors(label: str, payload: Mapping[str, Any]) -> None:
    seen_panic_owners: set[str] = set()
    for index, panic in enumerate(payload["panics"]):
        if not isinstance(panic, Mapping):
            raise RuntimeError(f"{label} panic row {index} must be an object")
        demanded_body = panic.get("demandedBody")
        demanded_source = panic.get("demandedSource")
        terminal_gap_locus = panic.get("terminalGapLocus")
        owner_identity = panic.get("ownerIdentity")
        gap = panic.get("gap")
        if (
            panic.get("kind") != "FactoryPanic"
            or panic.get("status") != "mandatory-panic"
            or not isinstance(panic.get("reason"), str)
            or not isinstance(panic.get("locus"), str)
            or not panic["locus"]
            or not isinstance(gap, Mapping)
        ):
            raise RuntimeError(f"{label} panic row {index} violates closed wire schema")
        if not isinstance(demanded_body, Mapping):
            raise RuntimeError(f"{label} panic row {index} lacks demandedBody identity")
        if not isinstance(demanded_source, str) or not demanded_source:
            raise RuntimeError(
                f"{label} panic row {index} lacks demandedSource identity"
            )
        if not isinstance(terminal_gap_locus, str) or not terminal_gap_locus:
            raise RuntimeError(
                f"{label} panic row {index} lacks terminalGapLocus identity"
            )
        typed_gap_locus = gap.get("blame") or gap.get("gap_locus")
        if terminal_gap_locus != typed_gap_locus:
            raise RuntimeError(
                f"{label} panic row {index} terminalGapLocus does not match typed gap locus"
            )
        expected_identity = {
            "demandedBody": dict(demanded_body),
            "demandedSource": demanded_source,
            "terminalGapLocus": terminal_gap_locus,
        }
        if owner_identity != expected_identity:
            raise RuntimeError(f"{label} panic row {index} has malformed ownerIdentity")
        identity_key = json.dumps(
            expected_identity, sort_keys=True, separators=(",", ":")
        )
        if identity_key in seen_panic_owners:
            raise RuntimeError(
                f"{label} frontier has duplicate recovered panic owner identity"
            )
        seen_panic_owners.add(identity_key)

    terminal_loci: dict[str, set[str]] = {}
    for field in ("panics", "effects", "suppressedDescendants"):
        terminal_loci[field] = {
            row.get("locus")
            for row in payload[field]
            if isinstance(row, Mapping) and isinstance(row.get("locus"), str)
        }
    for left, right in (
        ("panics", "effects"),
        ("panics", "suppressedDescendants"),
        ("effects", "suppressedDescendants"),
    ):
        overlap = terminal_loci[left] & terminal_loci[right]
        if overlap:
            raise RuntimeError(
                f"{label} terminal vectors {left}/{right} overlap at {sorted(overlap)!r}"
            )


def _validate_closed_frontier(
    label: str, payload: Mapping[str, Any], returncode: int
) -> None:
    census = payload.get("census")
    if not isinstance(census, Mapping):
        raise RuntimeError(f"{label} frontier artifact lacks a census receipt")
    if census.get("kind") != "recovered-frontier-census":
        raise RuntimeError(f"{label} frontier census receipt has the wrong kind")
    counts: dict[str, int] = {}
    for field in _CENSUS_FIELDS:
        value = census.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise RuntimeError(
                f"{label} frontier census field `{field}` must be a non-negative integer"
            )
        counts[field] = value

    source_files = counts["sourceFilesEnumerated"]
    body_demands = counts["sourceBodiesDemanded"]
    if body_demands != source_files:
        raise RuntimeError(
            f"{label} source body census mismatch: "
            f"enumerated={source_files} demanded={body_demands}"
        )

    _validate_terminal_vectors(label, payload)
    panics = payload["panics"]
    status = payload.get("status")
    if status == "valid-empty":
        if (
            source_files != 0
            or counts["auditLeavesCompleted"] != 0
            or panics
            or payload["effects"]
            or payload["suppressedDescendants"]
        ):
            raise RuntimeError(
                f"{label} valid-empty frontier requires a zero source census"
            )
        if returncode != 0:
            raise RuntimeError(
                f"{label} valid-empty frontier exited nonzero={returncode}"
            )
        return
    if status == "complete":
        if source_files == 0:
            raise RuntimeError(
                f"{label} empty corpus must use explicit status=valid-empty"
            )
        if panics or returncode != 0:
            raise RuntimeError(
                f"{label} complete frontier has panics or nonzero exit={returncode}"
            )
        return
    if status == "failed" and panics and returncode != 0:
        return
    raise RuntimeError(
        f"{label} producer terminal/fatal/incomplete frontier state "
        f"status={status!r} exit={returncode}"
    )


def mint_recovered_frontier(
    *,
    label: str,
    sugar_bin: Path,
    workspace: Path,
    root: Path,
    env: dict[str, str],
    output_dir: Path,
    runner: RunCommand,
) -> Mapping[str, Any]:
    """Run the one sanctioned recovered-construction-audit CLI lane."""
    frontier_path = output_dir / "frontier.json"
    frontier_path.unlink(missing_ok=True)
    result = runner(
        [
            os.fspath(sugar_bin),
            "lift",
            "--audit-frontier",
            "--continue-on-construction-gaps",
            "-o",
            os.fspath(frontier_path),
            os.fspath(workspace),
        ],
        root,
        env,
    )
    receipt = output_dir / "wall.frontier.txt"
    receipt.write_text(
        result.stdout
        + ("\n" if result.stdout and result.stderr else "")
        + result.stderr,
        encoding="utf-8",
    )
    if not frontier_path.is_file():
        combined = result.stdout + result.stderr
        tail = combined[-4000:] if combined else "<no output captured>"
        raise RuntimeError(
            f"{label} recovered frontier failed without frontier.json "
            f"exit={result.returncode}; last words follow:\n{tail}"
        )
    try:
        try:
            payload = json.loads(frontier_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{label} frontier.json was not valid JSON: {exc}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise RuntimeError(f"{label} frontier.json must be a JSON object")
        if payload.get("kind") != "recovered-construction-audit":
            raise RuntimeError(f"{label} frontier artifact has the wrong kind")
        if payload.get("recoveryOverride") is not True:
            raise RuntimeError(f"{label} frontier artifact lacks recovery override")
        for field in ("panics", "suppressedDescendants", "effects"):
            if not isinstance(payload.get(field), list):
                raise RuntimeError(
                    f"{label} frontier artifact field `{field}` must be a list"
                )
        _validate_closed_frontier(label, payload, result.returncode)
    except Exception:
        frontier_path.unlink(missing_ok=True)
        raise
    return payload
