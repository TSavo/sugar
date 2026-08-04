#!/usr/bin/env python3
"""R_swallowed_throw_second_mechanism — honorable throws must not be half-rewritten.

LAW OF ONE: AST shadows → Sugar → meaning. One mechanism. Catch-and-continue,
raw-source substitution after ``literal_eval`` failure, and dual-mode
``SoftUnresolved*Sugar`` survival are second mechanisms for unfinished Sugar:
they dress a gap as absence, identity mutation, or soft incomplete.

THROWING IS HONORABLE: unfinished work raises. The sin is rewriting the throw
into silence, a survivor list, a substituted value, or a soft sugar outside the
AST tower.

Axes (kept separate; never summed into a single threshold):

* ``R_construction_panic_soft_continue`` — ``except ConstructionPanic`` (or
  bare / BaseException that can hold it) then ``continue`` / survivor filter
  without pure re-raise.
* ``R_exception_soft_continue`` — ``except Exception`` then bare ``continue``
  in a production loop (manufactures absence for the next shot).
* ``R_soft_unresolved_sugar_return`` — production returns
  ``SoftUnresolvedWithSugar`` / ``SoftUnresolvedTrySugar`` (UNDECIDED as soft
  Incomplete).
* ``R_literal_eval_raw_substitution`` — ``literal_eval`` under ``try``, except
  assigns raw source text as the decoded value (meaning outside Sugar).

Enforcement ladder note: this auditor is larval. Retirement path:

* Prefer: delete the handler; let the throw rise (panic / SourceTreePanic).
* Climb: encode "no second mechanism" as unconstructable construction (typed
  doors that cannot catch) once the language allows; then DELETE this shell.
* What would hatch the shell: every production package forbids soft handlers
  by construction (or a compiler/type-level catch ban). Until then the auditor
  names live offenders and the replacement architecture per row.

Scope: production ``src/`` under sugar-lift-python-source, sugar-source-tree,
and sugar-lift-py-tests. Tests and measurement scripts are out of domain
(they may plant the sin as lying twins).

Exit 1 while any axis R > 0 or auditor_errors > 0. No baseline. Silence only
at stable zero.

Usage::

    python scripts/swallowed_throw_second_mechanism_law.py
    python scripts/swallowed_throw_second_mechanism_law.py --python-root PATH
"""

from __future__ import annotations

# Not the board. Named denominator only.
# See tests/test_one_authoritative_scoreboard.py.

from sugar_lift_py_tests.repo_root import (
    python_implementations_root,
    sugar_lift_py_tests_package_root,
)

SCOREBOARD_AUTHORITY = False

import argparse
import ast
from pathlib import Path
import sys
from typing import NamedTuple


class SwallowOffender(NamedTuple):
    path: str
    line: int
    axis: str
    kind: str
    note: str
    fix: str


_AXES = (
    "R_construction_panic_soft_continue",
    "R_exception_soft_continue",
    "R_soft_unresolved_sugar_return",
    "R_literal_eval_raw_substitution",
)

_SOFT_UNRESOLVED_NAMES = frozenset(
    {
        "SoftUnresolvedWithSugar",
        "SoftUnresolvedTrySugar",
    }
)

_PRODUCTION_PACKAGE_SRC = (
    "sugar-lift-python-source/src",
    "sugar-source-tree/src",
    "sugar-lift-py-tests/src",
)


def _handler_type_names(handler: ast.ExceptHandler) -> set[str]:
    names: set[str] = set()
    t = handler.type
    if t is None:
        names.add("<bare>")
        return names

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                walk(elt)

    walk(t)
    return names


def _body_has_continue(handler: ast.ExceptHandler) -> bool:
    for node in ast.walk(handler):
        if isinstance(node, ast.Continue):
            return True
    return False


def _soft_silence_body(handler: ast.ExceptHandler) -> bool:
    """Handler only silences: continue, pass, return None, or name = None."""
    if _body_has_continue(handler):
        return True
    body = [
        n
        for n in handler.body
        if not (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        )
    ]
    if not body:
        return True
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Continue):
            continue
        if isinstance(stmt, ast.Return) and (
            stmt.value is None
            or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)
        ):
            continue
        if isinstance(stmt, ast.Assign) and (
            isinstance(stmt.value, ast.Constant) and stmt.value.value is None
        ):
            continue
        if isinstance(stmt, ast.AnnAssign) and (
            isinstance(stmt.value, ast.Constant) and stmt.value.value is None
        ):
            continue
        # any other statement means not pure silence (may still be soft via continue above)
        return False
    return True


def _pure_reraise(handler: ast.ExceptHandler) -> bool:
    """Every path ends in raise; no continue/soft survivor assignment."""
    body = [
        n
        for n in handler.body
        if not (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        )
    ]
    if not body:
        return False
    if _body_has_continue(handler):
        return False

    def ends_raise(stmts: list[ast.stmt]) -> bool:
        if not stmts:
            return False
        last = stmts[-1]
        if isinstance(last, ast.Raise):
            return True
        if isinstance(last, ast.If):
            return (
                bool(last.orelse) and ends_raise(last.body) and ends_raise(last.orelse)
            )
        return False

    return ends_raise(body)


def _calls_literal_eval(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Attribute) and func.attr == "literal_eval":
            return True
        if isinstance(func, ast.Name) and func.id == "literal_eval":
            return True
    return False


# Call leaves that, when Exception-silenced, manufacture construction absence.
_CONSTRUCTION_DOOR_LEAVES = frozenset(
    {
        "_require_narrow_cm_ref",
        "function_contract_rows",
        "force_floor",
        "to_term",
        "require_narrow_cm_ref",
        "reduce_source_outcome",
    }
)


def _try_calls_construction_door(try_node: ast.Try) -> bool:
    for child in ast.walk(try_node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name) and func.id in _CONSTRUCTION_DOOR_LEAVES:
            return True
        if isinstance(func, ast.Attribute) and func.attr in _CONSTRUCTION_DOOR_LEAVES:
            return True
    return False


def _except_assigns_raw_source(handler: ast.ExceptHandler) -> bool:
    """True if except body assigns text/source slice to a value-like name."""
    for stmt in handler.body:
        if not isinstance(stmt, ast.Assign):
            continue
        for target in stmt.targets:
            if isinstance(target, ast.Name) and target.id in {
                "value",
                "decoded",
                "lit",
            }:
                # value = text / value = unit.source[...] / value = source[...]
                rhs = stmt.value
                if isinstance(rhs, ast.Name) and rhs.id in {
                    "text",
                    "source",
                    "raw",
                    "span_text",
                }:
                    return True
                if isinstance(rhs, ast.Subscript):
                    return True
                if (
                    isinstance(rhs, ast.Attribute)
                    and isinstance(rhs.value, ast.Name)
                    and rhs.value.id in {"unit", "node"}
                    and rhs.attr == "source"
                ):
                    return True
    return False


def _return_soft_unresolved(node: ast.Return) -> str | None:
    value = node.value
    if value is None:
        return None
    # return SoftUnresolvedWithSugar(...)
    if isinstance(value, ast.Call):
        func = value.func
        if isinstance(func, ast.Name) and func.id in _SOFT_UNRESOLVED_NAMES:
            return func.id
        if isinstance(func, ast.Attribute) and func.attr in _SOFT_UNRESOLVED_NAMES:
            return func.attr
    return None


def scan_file(path: Path, *, rel: str) -> list[SwallowOffender]:
    offenders: list[SwallowOffender] = []
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return [
            SwallowOffender(
                rel,
                0,
                "auditor_errors",
                "auditor-read-error",
                f"could not read source: {error}",
                "make the production source readable to the auditor",
            )
        ]
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        return [
            SwallowOffender(
                rel,
                int(error.lineno or 0),
                "auditor_errors",
                "auditor-parse-error",
                f"ast.parse failed: {error.msg}",
                "fix the production source so the auditor can read it",
            )
        ]

    for node in ast.walk(tree):
        if isinstance(node, ast.Return):
            soft = _return_soft_unresolved(node)
            if soft is not None:
                offenders.append(
                    SwallowOffender(
                        path=rel,
                        line=node.lineno,
                        axis="R_soft_unresolved_sugar_return",
                        kind="soft-unresolved-sugar-return",
                        note=(
                            f"return {soft}(...) is dual-mode soft survival — "
                            "UNDECIDED rendered as Incomplete outside the tower"
                        ),
                        fix=(
                            "delete the soft sugar return; let SourceTreePanic / "
                            "SugarNotWritten rise, or write the missing Sugar door"
                        ),
                    )
                )

        if not isinstance(node, ast.Try):
            continue

        try_has_literal_eval = _calls_literal_eval(node)
        for handler in node.handlers:
            names = _handler_type_names(handler)
            has_continue = _body_has_continue(handler)
            pure = _pure_reraise(handler)

            if try_has_literal_eval and _except_assigns_raw_source(handler):
                offenders.append(
                    SwallowOffender(
                        path=rel,
                        line=handler.lineno,
                        axis="R_literal_eval_raw_substitution",
                        kind="literal-eval-raw-source-substitution",
                        note=(
                            "literal_eval failure substituted raw source text as "
                            "Constant.value — meaning outside Sugar"
                        ),
                        fix=(
                            "delete the except survival; bare literal_eval — "
                            "decode or throw"
                        ),
                    )
                )

            catches_panic = bool(
                names & {"ConstructionPanic", "BaseException"}
            ) or names == {"<bare>"}
            if catches_panic and has_continue and not pure:
                offenders.append(
                    SwallowOffender(
                        path=rel,
                        line=handler.lineno,
                        axis="R_construction_panic_soft_continue",
                        kind="construction-panic-soft-continue",
                        note=(
                            "except ConstructionPanic (or BaseException/bare) "
                            "then continue — unfinished Floor sealed as absence "
                            "or survivor identity"
                        ),
                        fix=(
                            "rip the catch; ConstructionPanic must propagate. "
                            "Write the missing to_term / Floor; never keep survivors"
                        ),
                    )
                )

            # Bare Exception soft-silence is debt when it is a second mechanism
            # for unfinished construction: either loop-continue, or soft-None /
            # empty body around a construction door call.
            if names == {"Exception"} and not pure:
                door = _try_calls_construction_door(node)
                if has_continue or (door and _soft_silence_body(handler)):
                    offenders.append(
                        SwallowOffender(
                            path=rel,
                            line=handler.lineno,
                            axis="R_exception_soft_continue",
                            kind="exception-soft-continue",
                            note=(
                                "except Exception then soft silence swallows "
                                "honorable throws"
                                + (
                                    " around a construction door"
                                    if door
                                    else " (loop continue manufactures absence)"
                                )
                            ),
                            fix=(
                                "rip the catch; let the throw rise. Named gap "
                                "enrollment belongs only at a sanctioned membrane "
                                "with exact AST shape, never bare Exception silence"
                            ),
                        )
                    )

    return sorted(offenders)


def production_roots(python_root: Path) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    for rel in _PRODUCTION_PACKAGE_SRC:
        roots.append((rel, python_root / rel))
    return roots


def _swallowed_scan_scope(python_root: Path):
    """Declared production package population with structural self/auth-pin exclusion."""
    try:
        from sugar_lift_py_tests.idd.instrument_scan_scope import instrument_scan_scope
    except ImportError:
        import importlib.util

        path = (
            sugar_lift_py_tests_package_root()
            / "src"
            / "sugar_lift_py_tests"
            / "idd"
            / "instrument_scan_scope.py"
        )
        spec = importlib.util.spec_from_file_location("instrument_scan_scope", path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        import sys

        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        instrument_scan_scope = mod.instrument_scan_scope
    roots = [root for _prefix, root in production_roots(python_root)]
    if not roots:
        raise ValueError(
            "swallowed-throw production roots empty; refuse undeclared population"
        )
    return instrument_scan_scope(
        declared_roots=roots,
        instrument_self=Path(__file__).resolve(),
    )


def scan_python_root(python_root: Path) -> list[SwallowOffender]:
    scope = _swallowed_scan_scope(python_root)
    offenders: list[SwallowOffender] = []
    for prefix, root in production_roots(python_root):
        if not root.is_dir():
            offenders.append(
                SwallowOffender(
                    prefix,
                    0,
                    "auditor_errors",
                    "auditor-root-error",
                    "scan root is not a directory",
                    "restore the production package src tree",
                )
            )
            continue
        try:
            paths = sorted(root.rglob("*.py"))
        except OSError as error:
            offenders.append(
                SwallowOffender(
                    prefix,
                    0,
                    "auditor_errors",
                    "auditor-root-error",
                    f"could not enumerate scan root: {error}",
                    "restore the production package src tree",
                )
            )
            continue
        for path in paths:
            if "__pycache__" in path.parts:
                continue
            if not scope.admits(path):
                continue
            rel = f"{prefix}/{path.relative_to(root).as_posix()}"
            offenders.extend(scan_file(path, rel=rel))
    return sorted(offenders)


def axis_counts(offenders: list[SwallowOffender]) -> dict[str, int]:
    counts = {axis: 0 for axis in _AXES}
    counts["auditor_errors"] = 0
    for row in offenders:
        if row.axis == "auditor_errors" or row.kind.startswith("auditor-"):
            counts["auditor_errors"] += 1
        elif row.axis in counts:
            counts[row.axis] += 1
    return counts


def format_report(offenders: list[SwallowOffender]) -> str:
    counts = axis_counts(offenders)
    lines = [
        "swallowed_throw_second_mechanism_law",
        *(f"{axis} = {counts[axis]}" for axis in _AXES),
        f"auditor_errors = {counts['auditor_errors']}",
        "",
        "Replacement architecture: rip catch-and-continue; throw or write Sugar/Floor.",
        "Never substitute raw source as Constant.value. Never SoftUnresolved survival.",
        "",
        "Loci:",
    ]
    if not offenders:
        lines.append("(none)")
    for row in offenders:
        lines.append(
            f"{row.path}:{row.line}:{row.kind} [{row.axis}] — {row.note} | FIX: {row.fix}"
        )
    return "\n".join(lines)


def default_python_root() -> Path:
    # scripts/ → sugar-lift-py-tests → python/
    return python_implementations_root()


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python-root",
        type=Path,
        default=default_python_root(),
        help="implementations/python root (contains package dirs)",
    )
    args = parser.parse_args(argv)
    offenders = scan_python_root(args.python_root)
    counts = axis_counts(offenders)
    r_total = sum(counts[axis] for axis in _AXES)
    auditor_errors = counts["auditor_errors"]
    print(format_report(offenders))
    if r_total or auditor_errors:
        print(
            f"SWALLOWED-THROW LAW RED: R_total={r_total} "
            f"(axes={ {a: counts[a] for a in _AXES} }) "
            f"auditor_errors={auditor_errors}",
            file=sys.stderr,
        )
        return 1
    print("SWALLOWED-THROW LAW GREEN: all axes 0", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
