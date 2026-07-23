"""Measure pandas' FormattedValue construction frontier.

This is a family-local delta instrument, not a baseline gate.  For every
``FormattedValue`` in the installed pandas source tree it asks that node to
construct directly and distinguishes the node's own gap from a gap inherited
from one of its children.  Run the same command before and after the arm; the
change in ``direct_gap`` is the observed family delta.
"""

from __future__ import annotations

import argparse
import ast
import importlib.metadata
import importlib.util
import json
import logging
from collections import Counter
from pathlib import Path

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.backend import BackendCouldNotParse, materialize
from sugar_source_tree.cpython_adapter import _Handle
from sugar_source_tree.nodes import SourceUnit
from sugar_source_tree.panic import SourceTreePanic, SugarNotWritten


def _installed_package_root(package: str) -> Path:
    spec = importlib.util.find_spec(package)
    if spec is None or spec.origin is None:
        raise RuntimeError(f"could not locate installed package {package!r}")
    return Path(spec.origin).resolve().parent


def _shape(node) -> str:
    conversion = node.conversion
    has_spec = node.format_spec is not None
    if conversion != -1 and has_spec:
        return "conversion_and_format_spec"
    if conversion != -1:
        return "conversion_only"
    if has_spec:
        return "format_spec_only"
    return "plain"


def measure(root: Path) -> dict[str, object]:
    counts: Counter[str] = Counter()
    direct_by_shape: Counter[str] = Counter()
    blocked_by_child: Counter[str] = Counter()
    roll_call_blocked_by_child: Counter[str] = Counter()
    other_panics: Counter[str] = Counter()
    roll_call: Counter[str] = Counter()

    paths = sorted(
        path for path in root.rglob("*.py") if "__pycache__" not in path.parts
    )
    for path in paths:
        counts["files_total"] += 1
        try:
            source, filename, source_cid = path_source(path)
            parsed = ast.parse(source, filename=str(path))
            native_nodes = [
                node
                for node in ast.walk(parsed)
                if isinstance(node, ast.FormattedValue)
            ]
            if not native_nodes:
                counts["files_without_formatted_value"] += 1
                counts["files_completed"] += 1
                continue
            counts["files_with_formatted_value"] += 1
            unit = SourceUnit(
                filename=filename,
                source=source,
                source_cid=source_cid,
            )
            formatted_values = [
                materialize(unit, _Handle(unit, native_node))
                for native_node in native_nodes
            ]
            for node in formatted_values:
                counts["formatted_value_total"] += 1
                shape = _shape(node)
                counts[f"shape.{shape}"] += 1
                try:
                    node.sugar()
                except SugarNotWritten as panic:
                    if panic.owner == "FormattedValue.sugar":
                        counts["direct_gap"] += 1
                        direct_by_shape[shape] += 1
                    else:
                        counts["blocked_descendant_gap"] += 1
                        blocked_by_child[panic.observed.split(" at ", 1)[0]] += 1
                except SourceTreePanic as panic:
                    counts["other_source_tree_panic"] += 1
                    other_panics[type(panic).__name__] += 1
                else:
                    counts["built"] += 1

            function_nodes = [
                node
                for node in ast.walk(parsed)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and any(
                    isinstance(descendant, ast.FormattedValue)
                    for descendant in ast.walk(node)
                )
            ]
            for native_function in function_nodes:
                roll_call["functions_with_formatted_value"] += 1
                function = materialize(unit, _Handle(unit, native_function))
                try:
                    function.sugar()
                except SugarNotWritten as panic:
                    if panic.owner == "FormattedValue.sugar":
                        roll_call["direct_gap"] += 1
                    else:
                        roll_call["blocked_descendant_gap"] += 1
                        roll_call_blocked_by_child[
                            panic.observed.split(" at ", 1)[0]
                        ] += 1
                except SourceTreePanic as panic:
                    roll_call["other_source_tree_panic"] += 1
                    other_panics[type(panic).__name__] += 1
                except Exception as panic:
                    roll_call["other_function_failure"] += 1
                    other_panics[type(panic).__name__] += 1
                else:
                    roll_call["built"] += 1
            counts["files_completed"] += 1
        except BackendCouldNotParse:
            counts["files_could_not_parse"] += 1
        except (OSError, UnicodeError, SourceTreePanic) as panic:
            counts["files_other_failure"] += 1
            other_panics[type(panic).__name__] += 1

    return {
        "root": str(root),
        "counts": dict(sorted(counts.items())),
        "direct_gap_by_shape": dict(sorted(direct_by_shape.items())),
        "roll_call": dict(sorted(roll_call.items())),
        "roll_call_blocked_by_child": dict(sorted(roll_call_blocked_by_child.items())),
        "blocked_descendant_by_child": dict(sorted(blocked_by_child.items())),
        "other_panics": dict(sorted(other_panics.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="source root (default: installed pandas package)",
    )
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    root = (args.root or _installed_package_root("pandas")).resolve()
    report = measure(root)
    report["pandas_version"] = importlib.metadata.version("pandas")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
