#!/usr/bin/env python3
"""R_finite_cap_opaque_completions — finite work may not become opaque success.

A performance cap may avoid materializing authenticated finite construction, but
its over-cap arm must remain honest: a loud typed terminal or an exact/witnessed
symbolic representation.  It may not return an opaque ``Complete``, a generic
coordinate, or force-curried construction.

This is a baseline-free structural census.  R > 0 exits red.  File, parse, and
root failures are also loud structured errors rather than process crashes.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import NamedTuple, Sequence


class FiniteCapOpaqueCompletion(NamedTuple):
    path: str
    line: int
    kind: str
    expression: str
    note: str


_BOUND_WORDS = ("limit", "cap", "bound", "budget", "maximum", "max_")
_EXACT_COMPACT_CONSTRUCTORS = {
    "GroundSequenceRepetitionValue",
}


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception as exc:  # noqa: BLE001 - auditor must stay structured
        return f"<unparse-failed:{type(exc).__name__}>"


def _looks_like_bound(node: ast.AST) -> bool:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and abs(node.value) >= 8
    ):
        return True
    return any(
        isinstance(child, ast.Name)
        and any(word in child.id.lower() for word in _BOUND_WORDS)
        for child in ast.walk(node)
    )


def _looks_like_finite_cardinality(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and _name(child.func) == "len":
            return True
        if isinstance(child, ast.Name) and any(
            word in child.id.lower()
            for word in ("count", "length", "size", "cardinality", "repeated")
        ):
            return True
        if isinstance(child, ast.Attribute) and child.attr.lower() in {
            "cardinality",
            "count",
            "length",
            "size",
            "repeated",
        }:
            return True
    return False


def _is_finite_cap_test(node: ast.AST) -> bool:
    if not isinstance(node, ast.Compare):
        return False
    if not any(isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)) for op in node.ops):
        return False
    operands = (node.left, *node.comparators)
    return any(_looks_like_finite_cardinality(item) for item in operands) and any(
        _looks_like_bound(item) for item in operands
    )


def _call_has_true_keyword(node: ast.Call, keyword: str) -> bool:
    return any(
        item.arg == keyword
        and isinstance(item.value, ast.Constant)
        and item.value.value is True
        for item in node.keywords
    )


def _is_forbidden_cap_complete(node: ast.Call) -> bool:
    if _name(node.func).split(".")[-1] != "Complete" or not node.args:
        return False
    payload = node.args[0]
    constructor = (
        _name(payload.func).split(".")[-1]
        if isinstance(payload, ast.Call)
        else ""
    )
    # Over-cap Complete is closed by default.  Only an exact compact value whose
    # identity contains the finite constructor/elements/count is admitted.
    return constructor not in _EXACT_COMPACT_CONSTRUCTORS


def _forbidden_exit(
    node: ast.Return,
    helpers: dict[str, list[ast.Return]],
    resolving: frozenset[str] = frozenset(),
) -> tuple[str, ast.AST] | None:
    if node.value is None:
        return "finite-cap-none-success", node
    if isinstance(node.value, ast.Constant) and node.value.value is None:
        return "finite-cap-none-success", node.value
    if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
        helper = node.value.func.id
        if helper not in resolving:
            for returned in helpers.get(helper, ()):
                forbidden = _forbidden_exit(
                    returned, helpers, resolving | {helper}
                )
                if forbidden is not None:
                    return forbidden
    for child in ast.walk(node.value):
        if not isinstance(child, ast.Call):
            continue
        called = _name(child.func).split(".")[-1]
        if _call_has_true_keyword(child, "force_curry"):
            return "finite-cap-force-curry", child
        if called == "opaque_coordinate" or called.endswith("_coordinate"):
            return "finite-cap-opaque-coordinate", child
        if _is_forbidden_cap_complete(child):
            return "finite-cap-opaque-complete", child
    return None


def _returns_in(statements: Sequence[ast.stmt]) -> list[ast.Return]:
    returns: list[ast.Return] = []
    for statement in statements:
        returns.extend(
            child for child in ast.walk(statement) if isinstance(child, ast.Return)
        )
    return returns


def _over_cap_returns(tree: ast.AST, node: ast.If) -> list[ast.Return]:
    """Select only the comparison arm in which cardinality exceeds the bound."""
    assert isinstance(node.test, ast.Compare)
    if len(node.test.ops) != 1 or len(node.test.comparators) != 1:
        return _returns_in((*node.body, *node.orelse))
    left_is_cardinality = _looks_like_finite_cardinality(node.test.left)
    right_is_cardinality = _looks_like_finite_cardinality(node.test.comparators[0])
    op = node.test.ops[0]
    body_is_over = (
        left_is_cardinality and isinstance(op, (ast.Gt, ast.GtE))
    ) or (right_is_cardinality and isinstance(op, (ast.Lt, ast.LtE)))
    if body_is_over:
        return _returns_in(node.body)
    if node.orelse:
        return _returns_in(node.orelse)
    return _fallthrough_returns(tree, node)


def _fallthrough_returns(tree: ast.AST, cap_node: ast.If) -> list[ast.Return]:
    """Find the immediate over-cap fallthrough after an under-cap early return."""
    if cap_node.orelse:
        return []
    for parent in ast.walk(tree):
        for _field, value in ast.iter_fields(parent):
            if not isinstance(value, list):
                continue
            for index, statement in enumerate(value[:-1]):
                if statement is not cap_node:
                    continue
                following = value[index + 1]
                if isinstance(following, ast.Return):
                    return [following]
    return []


def scan_source(source: str, *, path: str) -> list[FiniteCapOpaqueCompletion]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [
            FiniteCapOpaqueCompletion(
                path,
                int(exc.lineno or 0),
                "auditor-parse-error",
                type(exc).__name__,
                f"ast.parse failed: {exc.msg}",
            )
        ]
    except Exception as exc:  # noqa: BLE001
        return [
            FiniteCapOpaqueCompletion(
                path,
                0,
                "auditor-parse-error",
                type(exc).__name__,
                f"ast.parse failed: {exc}",
            )
        ]

    offenders: list[FiniteCapOpaqueCompletion] = []
    seen: set[tuple[int, str]] = set()
    parents = {
        child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
    }

    # A force-curry inside a branch that has already authenticated a finite
    # collection is forbidden even when a second semantic fast-path condition,
    # rather than the numeric cap comparison itself, selects the exit.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _call_has_true_keyword(
            node, "force_curry"
        ):
            continue
        cursor = parents.get(node)
        finite_arm = False
        while cursor is not None:
            if isinstance(cursor, ast.If):
                test = _safe_unparse(cursor.test)
                if (
                    "elements is not None" in test
                    or "finite_elements is not None" in test
                    or (
                        "isinstance(" in test
                        and any(
                            word in test
                            for word in ("ListValue", "TupleValue", "ArrayLiteral")
                        )
                    )
                ):
                    finite_arm = True
                    break
            cursor = parents.get(cursor)
        if not finite_arm:
            continue
        key = (getattr(node, "lineno", 0) or 0, "finite-cap-force-curry")
        seen.add(key)
        offenders.append(
            FiniteCapOpaqueCompletion(
                path,
                key[0],
                key[1],
                _safe_unparse(node),
                (
                    "authenticated finite history may not be replaced by "
                    "force-curried opaque success"
                ),
            )
        )

    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not _is_finite_cap_test(node.test):
            continue
        helpers = {
            item.name: _returns_in(item.body)
            for item in ast.walk(tree)
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name
        }
        controlled = _over_cap_returns(tree, node)
        for returned in controlled:
            forbidden = _forbidden_exit(returned, helpers)
            if forbidden is None:
                continue
            kind, expression = forbidden
            key = (getattr(expression, "lineno", 0) or 0, kind)
            if key in seen:
                continue
            seen.add(key)
            offenders.append(
                FiniteCapOpaqueCompletion(
                    path,
                    key[0],
                    kind,
                    _safe_unparse(expression),
                    (
                        "finite authenticated work must end in a loud typed "
                        "terminal or an exact/witnessed symbolic value"
                    ),
                )
            )
    return offenders


def scan_roots(roots: Sequence[Path]) -> list[FiniteCapOpaqueCompletion]:
    offenders: list[FiniteCapOpaqueCompletion] = []
    for root in roots:
        if not root.exists():
            offenders.append(
                FiniteCapOpaqueCompletion(
                    root.as_posix(),
                    0,
                    "auditor-root-error",
                    "FileNotFoundError",
                    "scan root does not exist",
                )
            )
            continue
        paths = (root,) if root.is_file() else sorted(root.rglob("*.py"))
        for path in paths:
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                offenders.append(
                    FiniteCapOpaqueCompletion(
                        path.as_posix(),
                        0,
                        "auditor-read-error",
                        type(exc).__name__,
                        f"could not read source: {exc}",
                    )
                )
                continue
            try:
                rel = path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                rel = path.as_posix()
            offenders.extend(scan_source(source, path=f"{root.name}/{rel}"))
    return sorted(offenders, key=lambda row: (row.path, row.line, row.kind))


def r_finite_cap_opaque_completions(
    rows: Sequence[FiniteCapOpaqueCompletion],
) -> int:
    return sum(1 for row in rows if not row.kind.startswith("auditor-"))


def r_auditor_errors(rows: Sequence[FiniteCapOpaqueCompletion]) -> int:
    return sum(1 for row in rows if row.kind.startswith("auditor-"))


def _default_root() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests"


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", type=Path)
    args = parser.parse_args(argv)
    rows = scan_roots(tuple(args.roots) or (_default_root(),))
    for row in rows:
        print(json.dumps(row._asdict(), sort_keys=True))
    risk = r_finite_cap_opaque_completions(rows)
    errors = r_auditor_errors(rows)
    print(f"R_finite_cap_opaque_completions = {risk}")
    print(f"R_auditor_errors = {errors}")
    return 1 if risk or errors else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - final structured safety membrane
        print(
            json.dumps(
                {
                    "kind": "auditor-process-error",
                    "expression": type(exc).__name__,
                    "note": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
