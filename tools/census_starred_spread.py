#!/usr/bin/env python3
"""Classify pandas starred/spread sites against the construction roll call."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def _key(node) -> tuple[str, int, int, int, int]:
    span = node.line_col_span()
    return (node.kind, span.start_line, span.start_col, span.end_line, span.end_col)


def _role(node, parents):
    parent_info = parents.get(_key(node))
    if node.kind == "Keyword" and node.arg is None:
        return ("call_double_star", parent_info[0]) if parent_info else None
    if node.kind == "DictItem" and node.key is None:
        return ("literal_dict_double_star", parent_info[0]) if parent_info else None
    if node.kind != "Starred" or parent_info is None:
        return None

    parent, field = parent_info
    if parent.kind == "Call" and field == "args":
        return "call_star", parent
    if parent.kind in {"List", "Tuple", "Set"} and field == "elts":
        # A Starred inside a Store-context sequence is an assignment target.
        ancestor = parent
        while (info := parents.get(_key(ancestor))) is not None:
            ancestor, ancestor_field = info
            if ancestor.kind in {"Assign", "AnnAssign", "For", "Comprehension"}:
                if ancestor_field in {"targets", "target"}:
                    return "assignment_star", ancestor
                break
        return "literal_star", parent
    return "other_star", parent


def census(root: Path) -> dict:
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.tree import SourceFile

    counts: Counter[tuple[str, str]] = Counter()
    files = sorted(root.rglob("*.py"))
    defects: Counter[str] = Counter()
    completed = 0
    for index, path in enumerate(files, 1):
        try:
            reporter = CollectingReporter()
            source_file = SourceFile.from_path(path, reporter=reporter)
            nodes = list(source_file.nodes())
            parents = {}
            by_key = {}
            for parent in nodes:
                by_key.setdefault(_key(parent), parent)
                for field, _position, child in parent.children():
                    parents.setdefault(_key(child), (parent, field))

            for function in source_file.functions():
                try:
                    function.sugar()
                except SugarNotWritten:
                    pass

            direct = {_key(node) for node, _panic in reporter.gaps}
            present = {_key(node) for node in reporter.present}
            for key, node in by_key.items():
                classified = _role(node, parents)
                if classified is None:
                    continue
                role, owner = classified
                owner_key = _key(owner)
                if key in direct or owner_key in direct:
                    status = "direct_gap"
                elif owner_key in present:
                    status = "built"
                else:
                    status = "blocked_descendant"
                counts[(role, status)] += 1
            completed += 1
            if index % 100 == 0 or index == len(files):
                print(f"[{index}/{len(files)}] {path.relative_to(root)}", flush=True)
        except Exception as error:
            defects[type(error).__name__] += 1
            print(
                f"[{index}/{len(files)}] DEFECT {type(error).__name__} "
                f"{path.relative_to(root)}: {error}",
                flush=True,
            )

    result = {
        "root": str(root),
        "files_total": len(files),
        "files_completed": completed,
        "defects": dict(sorted(defects.items())),
        "roles": {
            role: {
                status: counts[(role, status)]
                for status in ("direct_gap", "blocked_descendant", "built")
            }
            for role in sorted({role for role, _status in counts})
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    sys.setrecursionlimit(100_000)
    result = census(args.root)
    return 1 if result["defects"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
