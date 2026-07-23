#!/usr/bin/env python3
"""Measure pandas' Tuple/List Assign construction frontier.

This is a live census, not a pinned threshold.  For every destructuring Assign
it asks the node itself to construct, then independently asks the RHS child only
to distinguish a direct Assign gap from a gap inherited from that child.  Run
the same command before and after the symbolic-unpack arm to read Delta R.
"""

from __future__ import annotations

import importlib.util
from collections import Counter, defaultdict
from pathlib import Path

from sugar_lift_python_source.source_oracle import SourceUnavailable
from sugar_source_tree.backend import BackendCouldNotParse
from sugar_source_tree.nodes import (
    Assign,
    List,
    Name,
    Starred,
    Tuple_,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _package_root(name: str) -> Path:
    spec = importlib.util.find_spec(name)
    if spec is None or spec.origin is None:
        raise SystemExit(f"source unavailable for installed package {name!r}")
    return Path(spec.origin).resolve().parent


def _target_shape(target) -> str:
    if not isinstance(target, (Tuple_, List)):
        return "not-destructuring"
    kind = "tuple" if isinstance(target, Tuple_) else "list"

    def classify(node) -> str:
        if isinstance(node, Name):
            return "name"
        if isinstance(node, Starred):
            return "starred"
        if isinstance(node, (Tuple_, List)):
            return "nested"
        return type(node).__name__.lower()

    roles = [classify(element) for element in target.elts]
    if roles and all(role == "name" for role in roles):
        detail = "flat-name"
    elif "starred" in roles:
        detail = "starred"
    elif "nested" in roles:
        detail = "nested"
    else:
        detail = "mixed-" + "+".join(sorted(set(roles)))
    return f"{kind}:{detail}"


def _builds(node) -> bool:
    try:
        node.sugar().desugar()
    except (SugarNotWritten, ConstructionPanic, Exception):
        return False
    return True


def main() -> int:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    parse_failures = 0

    for path in sorted(_package_root("pandas").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            source = SourceFile.from_path(path)
        except (BackendCouldNotParse, SourceUnavailable):
            parse_failures += 1
            continue

        for node in source.nodes():
            if not isinstance(node, Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, (Tuple_, List)):
                continue

            shape = _target_shape(target)
            counts[shape]["total"] += 1
            if not _builds(node.substitute({})):
                if not _builds(node.value):
                    counts[shape]["blocked_descendant"] += 1
                else:
                    counts[shape]["direct_gap"] += 1
            else:
                counts[shape]["built"] += 1

    totals: Counter[str] = Counter()
    print("pandas destructuring Assign construction frontier")
    print("shape\ttotal\tbuilt\tdirect_gap\tblocked_descendant")
    for shape in sorted(counts):
        row = counts[shape]
        totals.update(row)
        print(
            f"{shape}\t{row['total']}\t{row['built']}\t"
            f"{row['direct_gap']}\t{row['blocked_descendant']}"
        )
    print(
        f"TOTAL\t{totals['total']}\t{totals['built']}\t"
        f"{totals['direct_gap']}\t{totals['blocked_descendant']}"
    )
    print(f"could_not_parse_files={parse_failures}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
