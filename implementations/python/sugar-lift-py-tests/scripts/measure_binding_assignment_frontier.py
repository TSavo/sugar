"""Measure the honest pandas binding/assignment construction frontier.

The direct axis constructs each assignment statement itself.  The enclosing
axis constructs each function containing an assignment and attributes a loud
result to the deepest typed panic that escaped construction.  Shape counts are
syntax only; a shape is drainable only when its direct children construct.
"""

from __future__ import annotations

import argparse
import ast
import importlib.metadata
import importlib.util
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.backend import BackendCouldNotParse, materialize
from sugar_source_tree.cpython_adapter import _Handle
from sugar_source_tree.nodes import SourceUnit
from sugar_source_tree.panic import SourceTreePanic, SugarNotWritten


ASSIGNMENT = (ast.Assign, ast.AnnAssign, ast.AugAssign)


def _installed_package_root(package: str) -> Path:
    spec = importlib.util.find_spec(package)
    if spec is None or spec.origin is None:
        raise RuntimeError(f"could not locate installed package {package!r}")
    return Path(spec.origin).resolve().parent


def _target_shape(target: ast.AST) -> str:
    if isinstance(target, ast.Name):
        return "name"
    if isinstance(target, ast.Attribute):
        return "attribute"
    if isinstance(target, ast.Subscript):
        return "subscript"
    if isinstance(target, ast.Starred):
        return "starred"
    if isinstance(target, (ast.Tuple, ast.List)):
        children = ",".join(_target_shape(value) for value in target.elts)
        return f"{'tuple' if isinstance(target, ast.Tuple) else 'list'}[{children}]"
    return type(target).__name__


def _shape(node: ast.AST) -> str:
    if isinstance(node, ast.Assign):
        targets = [_target_shape(target) for target in node.targets]
        prefix = "single" if len(targets) == 1 else "chained"
        if isinstance(node.value, (ast.Tuple, ast.List)):
            rhs = "display"
        elif isinstance(node.value, ast.Name):
            rhs = "alias"
        elif isinstance(node.value, ast.Attribute):
            rhs = "attribute-read"
        elif isinstance(node.value, ast.Subscript):
            rhs = "subscript-read"
        elif isinstance(node.value, ast.Call):
            rhs = "call"
        else:
            rhs = "other"
        return f"Assign/{prefix}/{'='.join(targets)}/rhs={rhs}"
    if isinstance(node, ast.AnnAssign):
        value = "valued" if node.value is not None else "bare"
        return f"AnnAssign/{_target_shape(node.target)}/{value}"
    assert isinstance(node, ast.AugAssign)
    return f"AugAssign/{_target_shape(node.target)}/{type(node.op).__name__}"


def _panic_key(panic: BaseException) -> str:
    owner = getattr(panic, "owner", type(panic).__name__)
    observed = getattr(panic, "observed", "")
    requested = getattr(panic, "requested", "")
    return f"{owner}|{observed}|{requested}"


def measure(root: Path, *, direct_only: bool = False) -> dict[str, object]:
    counts: Counter[str] = Counter()
    direct: dict[str, Counter[str]] = defaultdict(Counter)
    enclosing: dict[str, Counter[str]] = defaultdict(Counter)
    roots: Counter[str] = Counter()

    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        counts["files_total"] += 1
        try:
            source, filename, source_cid = path_source(path)
            parsed = ast.parse(source, filename=str(path))
            native_assignments = [node for node in ast.walk(parsed) if isinstance(node, ASSIGNMENT)]
            if not native_assignments:
                counts["files_without_assignment"] += 1
                continue
            unit = SourceUnit(filename=filename, source=source, source_cid=source_cid)
            for native in native_assignments:
                shape = _shape(native)
                direct[shape]["total"] += 1
                node = materialize(unit, _Handle(unit, native))
                try:
                    node.sugar()
                except SugarNotWritten as panic:
                    own = getattr(panic, "owner", "") in {
                        "Assign.sugar", "AnnAssign.sugar", "AugAssign.sugar"
                    }
                    direct[shape]["direct_gap" if own else "blocked_descendant"] += 1
                    roots[_panic_key(panic)] += 1
                except SourceTreePanic as panic:
                    direct[shape]["other_typed_loud"] += 1
                    roots[_panic_key(panic)] += 1
                else:
                    direct[shape]["built"] += 1

            functions = [] if direct_only else [
                node for node in ast.walk(parsed)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and any(isinstance(child, ASSIGNMENT) for child in ast.walk(node))
            ]
            for native_function in functions:
                shapes = sorted({_shape(node) for node in ast.walk(native_function) if isinstance(node, ASSIGNMENT)})
                function = materialize(unit, _Handle(unit, native_function))
                try:
                    function.sugar()
                except SourceTreePanic as panic:
                    roots[_panic_key(panic)] += 1
                    for shape in shapes:
                        enclosing[shape]["loud"] += 1
                        enclosing[shape][f"root:{getattr(panic, 'owner', type(panic).__name__)}"] += 1
                except Exception as panic:
                    for shape in shapes:
                        enclosing[shape]["non_source_failure"] += 1
                        enclosing[shape][f"root:{type(panic).__name__}"] += 1
                else:
                    for shape in shapes:
                        enclosing[shape]["built"] += 1
            counts["files_completed"] += 1
        except BackendCouldNotParse:
            counts["files_could_not_parse"] += 1
        except (OSError, UnicodeError, SourceTreePanic) as panic:
            counts["files_other_failure"] += 1
            roots[_panic_key(panic)] += 1

    return {
        "root": str(root),
        "pandas_version": importlib.metadata.version("pandas"),
        "counts": dict(sorted(counts.items())),
        "direct_by_shape": {key: dict(sorted(value.items())) for key, value in sorted(direct.items())},
        "enclosing_by_shape": {key: dict(sorted(value.items())) for key, value in sorted(enclosing.items())},
        "root_panics": dict(sorted(roots.items(), key=lambda item: (-item[1], item[0]))),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--direct-only", action="store_true")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    root = (args.root or _installed_package_root("pandas")).resolve()
    print(json.dumps(measure(root, direct_only=args.direct_only), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
