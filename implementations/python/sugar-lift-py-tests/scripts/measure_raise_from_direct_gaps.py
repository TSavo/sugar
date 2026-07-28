#!/usr/bin/env python3
"""Measure direct and blocked ``raise ... from ...`` construction residue."""

from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from pathlib import Path

from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.tree import SourceFile


def classify_raise_from(
    raises: list[ast.Raise],
    gap_sites: set[tuple[str, int, int]],
    source: str,
) -> tuple[dict[str, int], dict[str, int]]:
    lines = source.splitlines()

    def site(node: ast.AST) -> tuple[str, int, int]:
        line = getattr(node, "lineno", -1)
        byte_col = getattr(node, "col_offset", -1)
        if line < 1 or byte_col < 0:
            return type(node).__name__, line, byte_col
        normalized_col = len(lines[line - 1].encode("utf-8")[:byte_col].decode("utf-8"))
        return type(node).__name__, line, normalized_col

    direct: Counter[str] = Counter()
    blocked: Counter[str] = Counter()
    for node in raises:
        if node.cause is None:
            continue
        direct_site = site(node)
        if direct_site in gap_sites:
            direct["raise_from"] += 1
            continue

        descendant_sites = {
            site(descendant) for descendant in ast.walk(node) if descendant is not node
        }
        if descendant_sites & gap_sites:
            blocked["raise_from"] += 1
    return dict(direct), dict(blocked)


def collect_gap_sites(reporter: CollectingReporter) -> set[tuple[str, int, int]]:
    sites = set()
    for node, _ in reporter.gaps:
        span = node.line_col_span()
        sites.add((node.kind, span.start_line, span.start_col))
    return sites


def measure(root: Path) -> dict[str, object]:
    syntax = Counter({"raise_from": 0, "without_cause": 0, "bare": 0})
    direct: Counter[str] = Counter()
    blocked: Counter[str] = Counter()
    construction_panics: list[dict[str, str]] = []
    selected_files = 0

    for path in sorted(root.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
            parsed = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue

        raises = [node for node in ast.walk(parsed) if isinstance(node, ast.Raise)]
        for node in raises:
            shape = (
                "bare"
                if node.exc is None
                else "raise_from" if node.cause is not None else "without_cause"
            )
            syntax[shape] += 1
        if not raises:
            continue

        selected_files += 1
        from sugar_lift_py_tests.lift_rpc import (
            open_source_file_for_construction,
        )

        reporter = CollectingReporter()
        try:
            source_file = open_source_file_for_construction(
                path, root=root, reporter=reporter
            )
            # This instrument owns Raise classification, so construct every
            # Raise directly. An unwritten enclosing function must not hide a
            # cause descendant, and an unrelated sibling gap must not label
            # the Raise blocked.
            for raise_node in (
                node for node in source_file.nodes() if node.kind == "Raise"
            ):
                descendant_gap = False
                for operand in (raise_node.exc, raise_node.cause):
                    if operand is None:
                        continue
                    try:
                        operand.sugar()
                    except SugarNotWritten:
                        descendant_gap = True
                if descendant_gap:
                    # A parent Raise gap is not direct while either operand is
                    # itself unwritten. The descendant's reporter row owns the
                    # blocked classification.
                    continue
                try:
                    raise_node.sugar()
                except SugarNotWritten:
                    # The reporter records the exact direct/descendant locus;
                    # continue so later Raise sites are still measured.
                    pass
        except Exception as panic:
            construction_panics.append(
                {
                    "path": str(path),
                    "type": type(panic).__name__,
                    "message": str(panic),
                }
            )

        gap_sites = collect_gap_sites(reporter)

        file_direct, file_blocked = classify_raise_from(raises, gap_sites, source)
        direct.update(file_direct)
        blocked.update(file_blocked)

    return {
        "selected_files": selected_files,
        "syntax": dict(syntax),
        "direct": dict(direct),
        "blocked_descendant": dict(blocked),
        "construction_panics": construction_panics,
    }


def exit_status(result: dict[str, object]) -> int:
    return 1 if result["direct"] or result["construction_panics"] else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    result = measure(args.root.resolve())
    print(json.dumps(result, sort_keys=True))
    return exit_status(result)


if __name__ == "__main__":
    raise SystemExit(main())
