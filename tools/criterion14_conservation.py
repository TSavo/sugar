#!/usr/bin/env python3
"""Criterion 14 conservation checker: total line accounting, the conservation law.

Part of #3686 / #3706. Spec (T, 2026-07-06, "Criterion 14 -- total line
accounting, the conservation law"): for every vendor corpus file, every
physical line must be accounted by `sugar lift --report --json` as exactly
one of:

    warrant  -- the line carries proofir (a followable CID chain to contracts)
    support  -- an inert line affirmatively classified as support (an
                assertion, not an absence)
    effect   -- a named typed effect with grounds pointing at the line

A line the report does not mention is the outlawed fourth state. This module
consumes the machine-readable JSON report emitted by `sugar lift --report
--json` -- never the `--visual` render, which is a human-facing text product
and is not eligible evidence for this ratchet (scraping ANSI/text for a
GREEN/RED count is exactly the practice this criterion supersedes).

As of #3706, `report_to_json` (implementations/rust/sugar-cli/src/
report_fmt.rs) grew a `lineAccounting` array: one entry per physical line
claimed as `warrant` (a discharged row with a followable
targetCid/propertyCid/callsiteBundleCid), `support` (an affirmatively inert
line: blank, import, docstring, or a bare def/class signature -- computed by
`cmd_lift::render_report_json` from source-file access `report_fmt` does not
have), or `effect` (a refused row: the row's callee names the effect, its
`reason` is the grounds). This checker reads that field directly rather than
re-deriving classification from `rows` -- the JSON `lineAccounting` array
is the single source of truth, and this module must never grow a second,
parallel classifier of the same lines.

Every physical line of the source file not present in `lineAccounting` is
unaccounted, and is reported as a residue with file:line. That residue count
IS the campaign meter for Criterion 14: R(unaccounted-lines-over-<vendor>)
should be read off this tool file-by-file, and driven to zero only by the
report schema (or the lift pipeline feeding it) growing real classification
coverage -- never by this checker inventing a lie to make the count look
smaller.
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


def _matches_file(entry_file: str, source_file: str) -> bool:
    # `lineAccounting` entries (like `rows`) carry whatever path the lift
    # workspace saw them at; match on suffix so callers can pass either the
    # workspace-relative path or an absolute source path without having to
    # reconstruct the workspace.
    return (
        entry_file == source_file
        or entry_file.endswith(source_file)
        or source_file.endswith(entry_file)
    )


def _line_accounting_for_file(
    report_json: Mapping[str, Any], source_file: str
) -> list[Mapping[str, Any]]:
    entries = report_json.get("lineAccounting")
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise TypeError("report field `lineAccounting` must be a JSON array")
    matched: list[Mapping[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise TypeError(f"report `lineAccounting` entry {index} must be a JSON object")
        entry_file = entry.get("file")
        if not isinstance(entry_file, str):
            continue
        if _matches_file(entry_file, source_file):
            matched.append(entry)
    return matched


def _lines_of_class(entries: Sequence[Mapping[str, Any]], class_name: str) -> frozenset[int]:
    lines: set[int] = set()
    for entry in entries:
        if entry.get("class") != class_name:
            continue
        line = entry.get("line")
        if isinstance(line, int) and line > 0:
            lines.add(line)
    return frozenset(lines)


def _warrant_line_numbers(entries: Sequence[Mapping[str, Any]]) -> frozenset[int]:
    """`lineAccounting` entries of class `warrant`: a discharged row with a
    followable CID chain, emitted by `report_fmt::row_line_accounting`
    (implementations/rust/sugar-cli/src/line_accounting.rs). This checker
    trusts the report's own classification rather than re-deriving it from
    `rows` -- re-deriving here would be exactly the second, parallel
    classifier the ONE WAY LAW (#3706) forbids.
    """
    return _lines_of_class(entries, "warrant")


def _support_line_numbers(entries: Sequence[Mapping[str, Any]]) -> frozenset[int]:
    """`lineAccounting` entries of class `support`: affirmatively-classified-
    inert lines (blank, import, docstring, bare def/class signature),
    emitted by `cmd_lift::render_report_json`'s
    `layer_support_line_accounting` using the same source-file access
    `report_fmt` does not have.
    """
    return _lines_of_class(entries, "support")


def _effect_line_numbers(entries: Sequence[Mapping[str, Any]]) -> frozenset[int]:
    """`lineAccounting` entries of class `effect`: a refused row whose callee
    names the effect and whose `reason` is the grounds, emitted by
    `report_fmt::row_line_accounting`.
    """
    return _lines_of_class(entries, "effect")


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

    entries = _line_accounting_for_file(report_json, file_key)
    warrant_lines = _warrant_line_numbers(entries)
    support_lines = _support_line_numbers(entries)
    effect_lines = _effect_line_numbers(entries)

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
