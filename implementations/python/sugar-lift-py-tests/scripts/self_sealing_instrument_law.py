#!/usr/bin/env python3
"""Self-sealing instrument law — unfalsifiable teeth and checker-synthesized evidence.

CLASS NAME
    SELF-SEALING INSTRUMENT

DEFINITION
    An instrument (test, auditor, report, or idd check) whose green state is
    produced by the checker itself, or is true under every reachable state of
    the system under test — so the tooth cannot discriminate a lying twin.

    Subclasses (closed set this auditor recognizes):

    1. SYNTHESIZED-EVIDENCE
       The checker invents the population or site it later asserts is non-empty
       / present. Canonical shape: ``if not observed: observed = [self/__file__/
       this auditor]``. Worked exemplar: ``tests/law_of_one_auditor.py`` inserting
       ``audit_law_of_one`` as a projection caller when the graph has none, then
       ``assert projection_calls``.

    2. TAUTOLOGICAL-ASSERT
       An ``assert`` that is true for all values of the language, or whose two
       sides are the same AST (``assert x == x``, ``assert True``,
       ``assert len(x) >= 0``). A conservation check that equals itself is this
       subclass wearing domain clothes.

    3. PRESENCE-ONLY-IDENTITY
       ``assert <identity-bearing field> is not None`` without pinning the
       authenticated value. Both a real TypeError coordinate and a forged
       placeholder can be non-None; the tooth passes under the illegal state.
       Identity-bearing names include ``exception_type_coordinate``,
       ``occurrence_id``, and kin.

ENFORCEMENT LADDER
    Rung: **auditor** (static recognition over test/idd source).

    Why not higher yet:
    - Type system: cannot forbid optional fields being non-None with the wrong
      value, nor forbid a test author from writing ``if not xs: xs = [...]``.
    - Construction door: production evidence types can seal minting (see
      LawOfOneEvidence), but the *test/auditor* surface that fabricates callers
      is open Python.
    - Panic at contact: a green test never runs production contact on the lie.

    Retirement path (name what would let this auditor delete itself):
    1. Evidence mints are sealed so only the production graph can construct
       caller/site sets; empty observed sets are typed Incomplete, not filled.
    2. Identity assertions are a typed helper ``assert_identity(got, expected)``
       that requires Eq on the coordinate term — ``is not None`` does not type.
    3. Assertion macros reject tautological AST (left.unparse == right.unparse).
    When those three hatch, delete this auditor.

Not the board. Sole Python corpus scoreboard remains
scripts/control_effect_recensus.py. See tests/test_one_authoritative_scoreboard.py.
"""

from __future__ import annotations

# Not the board.
SCOREBOARD_AUTHORITY = False

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SYNTHESIZED = "SYNTHESIZED-EVIDENCE"
TAUTOLOGICAL = "TAUTOLOGICAL-ASSERT"
PRESENCE_ONLY = "PRESENCE-ONLY-IDENTITY"

REQUIRED_FIX = {
    SYNTHESIZED: (
        "delete the fill-in of observed evidence with self/__file__/auditor; "
        "empty observation is a contract red (missing production callers), never "
        "a synthetic site. Assert only on graph-observed sites."
    ),
    TAUTOLOGICAL: (
        "replace with a discrimination that a lying twin can flip: assert equal "
        "to an independently observed expected value, or assert a property that "
        "fails under the illegal state. Never assert x == x or True."
    ),
    PRESENCE_ONLY: (
        "pin the authenticated identity term (e.g. exception_type_coordinate == "
        "ctor('python:exception_type_identity', [str_const('builtins'), "
        "str_const('TypeError')])); presence alone is not identity."
    ),
}

# Attribute / name suffixes that promise source-authenticated identity.
_IDENTITY_ATTRS = frozenset(
    {
        "exception_type_coordinate",
        "exception_type_mro",
        "occurrence_id",
        "raise_occurrence",
        "occurrence",
        "type_coordinate",
        "coordinate_cid",
        "exception_type",
        "authenticated_identity",
        "producer_node_owner",
    }
)

_SELF_NAME_MARKERS = frozenset(
    {
        "__file__",
        "__name__",
        "__qualname__",
    }
)


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    column: int
    violation_class: str
    observed: str

    @property
    def required_fix(self) -> str:
        return REQUIRED_FIX[self.violation_class]

    def to_value(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "class": self.violation_class,
            "observed": self.observed,
            "requiredFix": self.required_fix,
        }


def _attr_chain_terminal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _attr_chain_terminal(node.value)
    return None


def _is_identity_bearing(node: ast.AST) -> bool:
    terminal = _attr_chain_terminal(node)
    return terminal in _IDENTITY_ATTRS if terminal is not None else False


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 — best-effort display
        return type(node).__name__


def _mentions_self_or_file(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in _SELF_NAME_MARKERS:
            return True
        if isinstance(child, ast.Attribute) and child.attr in _SELF_NAME_MARKERS:
            return True
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            # EvidenceSite(..., audit_law_of_one.__name__) etc. still needs Call.
            pass
        if isinstance(child, ast.Call):
            func = child.func
            # Path(__file__), inspect.getsourcelines(audit_fn), Path(__file__).resolve()
            if isinstance(func, ast.Name) and func.id in {"Path", "inspect"}:
                return True
            if isinstance(func, ast.Attribute):
                if func.attr in {
                    "getsourcelines",
                    "getsourcefile",
                    "currentframe",
                    "resolve",
                }:
                    return True
                if isinstance(func.value, ast.Name) and func.value.id == "Path":
                    return True
    return False


def _is_empty_test(test: ast.AST, name: str) -> bool:
    """True for ``not name``, ``len(name) == 0``, ``name == []``, etc."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        if isinstance(test.operand, ast.Name) and test.operand.id == name:
            return True
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        left, op, right = test.left, test.ops[0], test.comparators[0]
        if isinstance(op, (ast.Eq, ast.Is)) and isinstance(left, ast.Name) and left.id == name:
            if isinstance(right, (ast.List, ast.Tuple, ast.Set)) and not right.elts:
                return True
            if isinstance(right, ast.Constant) and right.value in (0, None, False, ""):
                return True
        if isinstance(op, (ast.Eq, ast.Is)) and isinstance(right, ast.Name) and right.id == name:
            if isinstance(left, (ast.List, ast.Tuple, ast.Set)) and not left.elts:
                return True
        if isinstance(op, ast.Eq) and isinstance(left, ast.Call):
            if (
                isinstance(left.func, ast.Name)
                and left.func.id == "len"
                and left.args
                and isinstance(left.args[0], ast.Name)
                and left.args[0].id == name
                and isinstance(right, ast.Constant)
                and right.value == 0
            ):
                return True
    return False


def _assigns_name_to_self_synthesized(stmt: ast.AST, name: str) -> bool:
    """``name = [EvidenceSite(Path(__file__), ...)]`` or ``name = (...)`` with self."""
    if not isinstance(stmt, ast.Assign):
        return False
    if not any(isinstance(t, ast.Name) and t.id == name for t in stmt.targets):
        return False
    value = stmt.value
    if isinstance(value, (ast.List, ast.Tuple)):
        if not value.elts:
            return False
        return any(_mentions_self_or_file(elt) for elt in value.elts)
    if isinstance(value, ast.Call):
        # name = EvidenceSite(Path(__file__), ...) single fill
        return _mentions_self_or_file(value)
    return False


def _is_tautological_assert_test(test: ast.AST) -> str | None:
    if isinstance(test, ast.Constant) and test.value is True:
        return "assert True"
    if isinstance(test, ast.Constant) and test.value == 1:
        return "assert 1"
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        left, op, right = test.left, test.ops[0], test.comparators[0]
        left_s, right_s = _unparse(left), _unparse(right)
        # Identical pure names/attrs: always true. Identical CALLS are often
        # intentional determinism/purity twins (f() == f()) — those CAN fail.
        if left_s == right_s and isinstance(op, (ast.Eq, ast.Is, ast.GtE, ast.LtE)):
            left_has_call = any(isinstance(n, ast.Call) for n in ast.walk(left))
            right_has_call = any(isinstance(n, ast.Call) for n in ast.walk(right))
            if not left_has_call and not right_has_call:
                return f"assert {_unparse(test)} (identical sides)"
        # len(x) >= 0 always true
        if (
            isinstance(op, ast.GtE)
            and isinstance(left, ast.Call)
            and isinstance(left.func, ast.Name)
            and left.func.id == "len"
            and isinstance(right, ast.Constant)
            and right.value == 0
        ):
            return "assert len(...) >= 0 (always true)"
        if (
            isinstance(op, ast.LtE)
            and isinstance(right, ast.Call)
            and isinstance(right.func, ast.Name)
            and right.func.id == "len"
            and isinstance(left, ast.Constant)
            and left.value == 0
        ):
            return "assert 0 <= len(...) (always true)"
    return None


def _is_presence_only_identity(test: ast.AST) -> str | None:
    """``x is not None`` / ``x != None`` on identity-bearing field."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    left, op, right = test.left, test.ops[0], test.comparators[0]
    if isinstance(op, ast.IsNot) and isinstance(right, ast.Constant) and right.value is None:
        if _is_identity_bearing(left):
            return f"assert {_unparse(left)} is not None (presence-only identity)"
    if isinstance(op, ast.NotEq) and isinstance(right, ast.Constant) and right.value is None:
        if _is_identity_bearing(left):
            return f"assert {_unparse(left)} != None (presence-only identity)"
    # flipped: None is not x
    if isinstance(op, ast.IsNot) and isinstance(left, ast.Constant) and left.value is None:
        if _is_identity_bearing(right):
            return f"assert None is not {_unparse(right)} (presence-only identity)"
    return None


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.findings: list[Finding] = []

    def _add(self, node: ast.AST, kind: str, observed: str) -> None:
        self.findings.append(
            Finding(
                path=self.path,
                line=getattr(node, "lineno", 1) or 1,
                column=getattr(node, "col_offset", 0) or 0,
                violation_class=kind,
                observed=observed,
            )
        )

    def visit_If(self, node: ast.If) -> None:
        # if not name: name = [self-synthesized]
        for candidate in _names_tested_empty(node.test):
            for stmt in node.body:
                if _assigns_name_to_self_synthesized(stmt, candidate):
                    self._add(
                        stmt,
                        SYNTHESIZED,
                        f"if-not-{candidate}: fill {candidate} with self/__file__/"
                        f"auditor-synthesized evidence ({_unparse(stmt)})",
                    )
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        taut = _is_tautological_assert_test(node.test)
        if taut is not None:
            self._add(node, TAUTOLOGICAL, taut)
        presence = _is_presence_only_identity(node.test)
        if presence is not None:
            self._add(node, PRESENCE_ONLY, presence)
        self.generic_visit(node)


def _names_tested_empty(test: ast.AST) -> list[str]:
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        if isinstance(test.operand, ast.Name):
            return [test.operand.id]
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        left, op, right = test.left, test.ops[0], test.comparators[0]
        if isinstance(left, ast.Name) and _is_empty_test(test, left.id):
            return [left.id]
        if (
            isinstance(left, ast.Call)
            and isinstance(left.func, ast.Name)
            and left.func.id == "len"
            and left.args
            and isinstance(left.args[0], ast.Name)
            and isinstance(op, ast.Eq)
            and isinstance(right, ast.Constant)
            and right.value == 0
        ):
            return [left.args[0].id]
    return []


def scan_python_source(source: str, path: str) -> list[Finding]:
    tree = ast.parse(source, filename=path)
    visitor = _Visitor(path)
    visitor.visit(tree)
    return sorted(set(visitor.findings))


def _default_roots(repo: Path) -> tuple[Path, ...]:
    return (
        repo / "tests",
        repo / "implementations/python/sugar-lift-py-tests/tests",
        repo / "implementations/python/sugar-source-tree/tests",
        repo / "implementations/python/sugar-lift-python-source/tests",
        repo / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/idd",
    )


def _source_files(roots: Iterable[Path]) -> list[Path]:
    files: set[Path] = set()
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            files.add(root)
        elif root.is_dir():
            for path in root.rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                # Do not scan this law's own unit tests as live corpus noise
                # for the planted twins file — still scan it; twins are in
                # strings so they do not fire. Live corpus is fine.
                files.add(path)
    return sorted(files)


def scan_roots(
    roots: Iterable[Path], *, repo: Path | None = None
) -> tuple[list[Finding], list[str]]:
    base = (repo or Path.cwd()).resolve()
    findings: list[Finding] = []
    errors: list[str] = []
    # Never audit this script as an offender source of examples in docstrings
    # with executable code — docstrings are not AST statements. Fine.
    self_path = Path(__file__).resolve()
    for path in _source_files(roots):
        if path.resolve() == self_path:
            continue
        label = (
            str(path.resolve().relative_to(base))
            if path.resolve().is_relative_to(base)
            else str(path)
        )
        try:
            source = path.read_text(encoding="utf-8")
            findings.extend(scan_python_source(source, label))
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
    return sorted(set(findings)), sorted(errors)


def format_report(findings: Iterable[Finding], errors: Iterable[str] = ()) -> str:
    rows = list(findings)
    error_rows = list(errors)
    lines = [
        "SELF-SEALING INSTRUMENT AUDIT",
        "rung=auditor",
        "retire_when="
        "sealed evidence mints + typed assert_identity(Eq) + tautology-rejecting "
        "assert macro make this class unrepresentable",
        "",
    ]
    for finding in rows:
        lines.append(
            f"{finding.path}:{finding.line}:{finding.column}: {finding.violation_class}: "
            f"{finding.observed}; required fix: {finding.required_fix}"
        )
    lines.extend(f"AUDITOR-ERROR: {error}" for error in error_rows)
    by_class = {
        kind: sum(row.violation_class == kind for row in rows) for kind in REQUIRED_FIX
    }
    lines.append(f"R_self_sealing_instruments = {len(rows)}")
    for kind, count in by_class.items():
        axis = kind.lower().replace("-", "_")
        lines.append(f"R_{axis} = {count}")
    lines.append(f"R_auditor_errors = {len(error_rows)}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    roots = tuple(path.resolve() for path in args.roots) or _default_roots(repo)
    findings, errors = scan_roots(roots, repo=repo)
    print(format_report(findings, errors))
    if args.json is not None:
        args.json.write_text(
            json.dumps(
                {
                    "kind": "self-sealing-instrument-audit",
                    "class": "SELF-SEALING INSTRUMENT",
                    "rung": "auditor",
                    "R": len(findings),
                    "auditorErrors": errors,
                    "byClass": {
                        kind: sum(f.violation_class == kind for f in findings)
                        for kind in REQUIRED_FIX
                    },
                    "findings": [finding.to_value() for finding in findings],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return 1 if findings or errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
