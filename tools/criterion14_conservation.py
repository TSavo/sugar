#!/usr/bin/env python3
"""Criterion 14 conservation checker: total line accounting, the conservation law.

Part of #3686. Spec (T, 2026-07-06, "Criterion 14 -- total line accounting,
the conservation law"): for every vendor corpus file, every physical line must
be accounted by `sugar lift --report --json` as exactly one of:

    warrant  -- the line carries proofir (a followable CID chain to contracts)
    support  -- an inert line affirmatively classified as support (an
                assertion, not an absence)
    effect   -- a named typed effect with grounds pointing at the line

A line the report does not mention is the outlawed fourth state. This module
consumes the machine-readable JSON report emitted by `sugar lift --report
--json` -- never the `--visual` render, which is a human-facing text product
and is not eligible evidence for this ratchet (scraping ANSI/text for a
GREEN/RED count is exactly the practice this criterion supersedes).

Today's report schema (implementations/rust/sugar-cli/src/report_fmt.rs)
only emits `rows` (one row per callsite carrying a contract, each with a
`file`/`line`/`status`) and `callEdges`/`toolchainPlans`/`superposition`
side-channels. It has no `support` or `effect` field at all. That is not a
bug this module papers over: it is measured as a finding. Concretely, this
checker classifies:

    warrant -- physical lines that are the `line` of some row whose
               `status` == "discharged" (the row carries a followable CID:
               `targetCid`/`propertyCid`/`callsiteBundleCid`).
    support -- NOT YET EXPRESSIBLE. The current report has no field an
               affirmative "this line is inert, on purpose" claim could
               live in. Zero lines are ever classified support today.
    effect  -- NOT YET EXPRESSIBLE. The current report has no typed-effect
               field with grounds. Zero lines are ever classified effect
               today.

Every physical line of the source file that is not a warrant line is
therefore unaccounted, and is reported as a residue with file:line. That
residue count IS the campaign meter for Criterion 14: R(unaccounted-lines-
over-<vendor>) should be read off this tool file-by-file, and driven to zero
only by the report schema growing real `support`/`effect` classification
(never by this checker inventing a lie to make the count look smaller).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class LineResidue:
    """A single unaccounted physical line: neither warrant, support, nor effect."""

    file: str
    line: int

    def locator(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass(frozen=True)
class ConservationResult:
    file: str
    total_lines: int
    warrant_lines: frozenset[int]
    support_lines: frozenset[int]
    effect_lines: frozenset[int]
    unaccounted: tuple[LineResidue, ...]

    @property
    def warrant(self) -> int:
        return len(self.warrant_lines)

    @property
    def support(self) -> int:
        return len(self.support_lines)

    @property
    def effect(self) -> int:
        return len(self.effect_lines)

    @property
    def residue(self) -> int:
        """R(unaccounted-lines-over-<file>): the conservation ratchet value."""
        return len(self.unaccounted)

    def conserved(self) -> bool:
        return self.residue == 0

    def to_json(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "totalLines": self.total_lines,
            "warrant": self.warrant,
            "support": self.support,
            "effect": self.effect,
            "residue": self.residue,
            "unaccounted": [
                {"file": r.file, "line": r.line} for r in self.unaccounted
            ],
        }


def _rows_for_file(report_json: Mapping[str, Any], source_file: str) -> list[Mapping[str, Any]]:
    rows = report_json.get("rows")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise TypeError("report field `rows` must be a JSON array")
    matched: list[Mapping[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TypeError(f"report `rows` entry {index} must be a JSON object")
        row_file = row.get("file")
        if not isinstance(row_file, str):
            continue
        # Rows carry whatever path the lift workspace saw them at; match on
        # suffix so callers can pass either the workspace-relative path or an
        # absolute source path without having to reconstruct the workspace.
        if row_file == source_file or row_file.endswith(source_file) or source_file.endswith(row_file):
            matched.append(row)
    return matched


def _warrant_line_numbers(rows: Sequence[Mapping[str, Any]]) -> frozenset[int]:
    """A row is a warrant only if it is discharged AND carries a followable CID.

    "Carries proofir" is not satisfied by a bare status string: the spec
    requires a *followable CID chain to contracts*. A discharged row with no
    targetCid/propertyCid/callsiteBundleCid is not a warrant -- it is a
    schema gap, and its line stays unaccounted rather than being waved
    through on status alone.
    """
    lines: set[int] = set()
    for row in rows:
        if row.get("status") != "discharged":
            continue
        has_cid = any(
            isinstance(row.get(field_name), str) and row.get(field_name).strip()
            for field_name in ("targetCid", "propertyCid", "callsiteBundleCid")
        )
        if not has_cid:
            continue
        line = row.get("line")
        if isinstance(line, int) and line > 0:
            lines.add(line)
    return frozenset(lines)


def _support_line_numbers(rows: Sequence[Mapping[str, Any]]) -> frozenset[int]:
    """No field in today's report schema can express "affirmatively inert".

    Kept as its own function (rather than inlined as `frozenset()`) so the
    day the report grows a real support classification, only this function
    needs to change -- the conservation law and its test do not.
    """
    return frozenset()


def _effect_line_numbers(rows: Sequence[Mapping[str, Any]]) -> frozenset[int]:
    """No field in today's report schema can express a named typed effect.

    See `_support_line_numbers`: kept separate so growing the schema is a
    one-function change, not a rewrite of the checker.
    """
    return frozenset()


def check_conservation(
    report_json: Mapping[str, Any], source_path: Path, *, report_file_key: str | None = None
) -> ConservationResult:
    """Classify every physical line of `source_path` against `report_json`.

    `report_file_key` overrides the file identity used to match rows in the
    report (defaults to `source_path.name`, since lift workspaces commonly
    relocate the vendor tree and rows carry workspace-relative paths).
    """
    text = source_path.read_text()
    total_lines = len(text.splitlines())
    file_key = report_file_key or source_path.name

    rows = _rows_for_file(report_json, file_key)
    warrant_lines = _warrant_line_numbers(rows)
    support_lines = _support_line_numbers(rows)
    effect_lines = _effect_line_numbers(rows)

    claimed = warrant_lines | support_lines | effect_lines
    unaccounted = tuple(
        LineResidue(file=file_key, line=n)
        for n in range(1, total_lines + 1)
        if n not in claimed
    )

    return ConservationResult(
        file=file_key,
        total_lines=total_lines,
        warrant_lines=warrant_lines,
        support_lines=support_lines,
        effect_lines=effect_lines,
        unaccounted=unaccounted,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_json", type=Path, help="path to `sugar lift --report --json` output")
    parser.add_argument("source_file", type=Path, nargs="+", help="vendor source file(s) to check")
    parser.add_argument(
        "--report-file-key",
        default=None,
        help="override the file identity used to match report rows (default: source basename)",
    )
    parser.add_argument(
        "--max-residue",
        type=int,
        default=0,
        help="fail only if residue exceeds this many lines per file (default: 0, the law itself)",
    )
    args = parser.parse_args(argv)

    report_json = json.loads(args.report_json.read_text())
    if not isinstance(report_json, Mapping):
        print("report JSON must be a JSON object", file=sys.stderr)
        return 2

    overall_bad = False
    for source_file in args.source_file:
        result = check_conservation(
            report_json, source_file, report_file_key=args.report_file_key
        )
        print(json.dumps(result.to_json(), indent=2))
        if result.residue > args.max_residue:
            overall_bad = True
            for r in result.unaccounted:
                print(f"UNACCOUNTED {r.locator()}", file=sys.stderr)
            print(
                f"R(unaccounted-lines-over-{result.file}) = {result.residue} "
                f"> allowed {args.max_residue}",
                file=sys.stderr,
            )

    return 1 if overall_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
