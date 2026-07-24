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
from sugar_lift_py_tests.audit_only.collect_construction_gaps import (
    collect_construction_panic,
)
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


def _gap_key(info: dict[str, str]) -> str:
    return "|".join(info.get(field, "") for field in ("owner", "observed", "requested"))


def _plain_class_names(module: ast.Module) -> frozenset[str]:
    forbidden = {
        "__new__",
        "__getattr__",
        "__getattribute__",
        "__setattr__",
        "__delattr__",
        "__getitem__",
        "__setitem__",
        "__delitem__",
    }
    return frozenset(
        node.name
        for node in module.body
        if isinstance(node, ast.ClassDef)
        and not node.bases
        and not node.keywords
        and not node.decorator_list
        and all(isinstance(member, (ast.Pass, ast.FunctionDef)) for member in node.body)
        and all(
            not isinstance(member, ast.FunctionDef)
            or (member.name not in forbidden and not member.decorator_list)
            for member in node.body
        )
    )


def _has_object_field_candidate(
    function: ast.AST, plain_class_names: frozenset[str]
) -> bool:
    """Structural measurement label, never construction authority."""
    constructed_names = {
        target.id
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and (
            isinstance(node.value, (ast.Dict, ast.List))
            or (
                isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id in plain_class_names
            )
        )
        for target in node.targets
    }
    return any(
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], (ast.Attribute, ast.Subscript))
        and isinstance(node.targets[0].value, ast.Name)
        and node.targets[0].value.id in constructed_names
        for node in ast.walk(function)
    )


def measure(
    root: Path, *, direct_only: bool = False, object_field_only: bool = False
) -> dict[str, object]:
    counts: Counter[str] = Counter()
    direct: dict[str, Counter[str]] = defaultdict(Counter)
    enclosing: dict[str, Counter[str]] = defaultdict(Counter)
    enclosing_functions: Counter[str] = Counter()
    object_field_enclosing: Counter[str] = Counter()
    object_field_rows: list[dict[str, object]] = []
    roots: Counter[str] = Counter()

    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        counts["files_total"] += 1
        try:
            source, filename, source_cid = path_source(path)
            parsed = ast.parse(source, filename=str(path))
            plain_class_names = _plain_class_names(parsed)
            native_assignments = [
                node for node in ast.walk(parsed) if isinstance(node, ASSIGNMENT)
            ]
            if not native_assignments:
                counts["files_without_assignment"] += 1
                continue
            unit = SourceUnit(filename=filename, source=source, source_cid=source_cid)
            for native in (() if object_field_only else native_assignments):
                shape = _shape(native)
                direct[shape]["total"] += 1
                node = materialize(unit, _Handle(unit, native))
                try:
                    _, gap = collect_construction_panic(
                        f"{path}:{getattr(native, 'lineno', 0)}", node.sugar
                    )
                except SugarNotWritten as panic:
                    own = getattr(panic, "owner", "") in {
                        "Assign.sugar",
                        "AnnAssign.sugar",
                        "AugAssign.sugar",
                    }
                    direct[shape]["direct_gap" if own else "blocked_descendant"] += 1
                    roots[_panic_key(panic)] += 1
                except SourceTreePanic as panic:
                    direct[shape]["other_typed_loud"] += 1
                    roots[_panic_key(panic)] += 1
                else:
                    if gap is None:
                        direct[shape]["built"] += 1
                    else:
                        direct[shape]["construction_panic"] += 1
                        roots[_gap_key(gap.info)] += 1

            functions = (
                []
                if direct_only
                else [
                    node
                    for node in ast.walk(parsed)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and any(isinstance(child, ASSIGNMENT) for child in ast.walk(node))
                    and (
                        not object_field_only
                        or _has_object_field_candidate(node, plain_class_names)
                    )
                ]
            )
            for native_function in functions:
                enclosing_functions["total"] += 1
                object_field_candidate = _has_object_field_candidate(
                    native_function, plain_class_names
                )
                if object_field_candidate:
                    object_field_enclosing["total"] += 1
                row = {
                    "path": str(path.relative_to(root)),
                    "line": native_function.lineno,
                    "function": native_function.name,
                }
                shapes = sorted(
                    {
                        _shape(node)
                        for node in ast.walk(native_function)
                        if isinstance(node, ASSIGNMENT)
                    }
                )
                function = materialize(unit, _Handle(unit, native_function))
                try:
                    _, gap = collect_construction_panic(
                        f"{path}:{native_function.lineno}", function.sugar
                    )
                except SourceTreePanic as panic:
                    enclosing_functions["typed_loud"] += 1
                    if object_field_candidate:
                        object_field_enclosing["typed_loud"] += 1
                        object_field_rows.append(
                            {**row, "status": "typed_loud", "error": str(panic)}
                        )
                    roots[_panic_key(panic)] += 1
                    for shape in shapes:
                        enclosing[shape]["loud"] += 1
                        enclosing[shape][
                            f"root:{getattr(panic, 'owner', type(panic).__name__)}"
                        ] += 1
                except Exception as panic:
                    enclosing_functions["non_source_failure"] += 1
                    if object_field_candidate:
                        object_field_enclosing["non_source_failure"] += 1
                        object_field_rows.append(
                            {
                                **row,
                                "status": "non_source_failure",
                                "error": f"{type(panic).__name__}: {panic}",
                            }
                        )
                    for shape in shapes:
                        enclosing[shape]["non_source_failure"] += 1
                        enclosing[shape][f"root:{type(panic).__name__}"] += 1
                else:
                    if gap is None:
                        enclosing_functions["built"] += 1
                        if object_field_candidate:
                            object_field_enclosing["built"] += 1
                            object_field_rows.append({**row, "status": "built"})
                        for shape in shapes:
                            enclosing[shape]["built"] += 1
                    else:
                        owner = gap.info.get("owner", "ConstructionPanic")
                        enclosing_functions["construction_panic"] += 1
                        if object_field_candidate:
                            object_field_enclosing["construction_panic"] += 1
                            object_field_rows.append(
                                {
                                    **row,
                                    "status": "construction_panic",
                                    "error": gap.message,
                                }
                            )
                        roots[_gap_key(gap.info)] += 1
                        for shape in shapes:
                            enclosing[shape]["construction_panic"] += 1
                            enclosing[shape][f"root:{owner}"] += 1
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
        "direct_by_shape": {
            key: dict(sorted(value.items())) for key, value in sorted(direct.items())
        },
        "enclosing_by_shape": {
            key: dict(sorted(value.items())) for key, value in sorted(enclosing.items())
        },
        "enclosing_functions": dict(sorted(enclosing_functions.items())),
        "object_field_enclosing": dict(sorted(object_field_enclosing.items())),
        "object_field_rows": object_field_rows,
        "root_panics": dict(
            sorted(roots.items(), key=lambda item: (-item[1], item[0]))
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--direct-only", action="store_true")
    parser.add_argument("--object-field-only", action="store_true")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    root = (args.root or _installed_package_root("pandas")).resolve()
    print(
        json.dumps(
            measure(
                root,
                direct_only=args.direct_only,
                object_field_only=args.object_field_only,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
