"""Python Layer-0 leaf-assertion harvester (verify-facing).

The Python analog of Go's ``lifgotests.LiftLeafAssertions`` (PR #1445). It
harvests each single recognized ``assert`` statement in a pytest test function
into its own ``contract`` declaration whose ``inv`` is the lifted
``=(<call>, <expected>)`` formula::

    def test_double():
        assert double(3) == 6      ->  contract{ inv = =(double(3), 6) }

where ``double(3)`` is a ``ctor`` named ``double`` -- exactly the harvested
``=(<call>, <expected>)`` callsite the verifier's body-discharge seam
enumerates and reduces through the body-derived ``function-contract`` for
``double``. One contract per test function (``inv`` is the conjunction of that
test's recognized assertions; the common single-assertion case is the bare
``=( ... )``), so a function-contract bridge can match it.

Whitelist (v0), each side an operand (identifier var / int literal / single-arg
call ``f(arg)`` as a ctor / negative-int literal):

    assert <lhs> == <rhs>   -> = (lhs, rhs)
    assert <lhs> != <rhs>   -> ≠ (lhs, rhs)
    assert <lhs> <  <rhs>   -> < (lhs, rhs)        (and <=, >, >=)
    assert <lhs> is None    -> and(=(lhs, None), is_none(lhs))
    assert <lhs> is not None -> and(≠(lhs, None), is_some(lhs))

Anything else is skipped (a diagnostic, not a contract) so the harvester never
fabricates a callsite it cannot faithfully lift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Any

_tree_src = Path(__file__).resolve().parents[3] / "sugar-source-tree" / "src"
if _tree_src.is_dir() and str(_tree_src) not in sys.path:
    sys.path.insert(0, str(_tree_src))

from sugar_source_tree.backend import BackendCouldNotParse
from sugar_source_tree.nodes import (
    Assert,
    Call,
    Compare,
    Constant,
    Expression,
    FunctionDef,
    Name,
    UnaryOp,
)
from sugar_source_tree.tree import SourceFile

from .canonical import blake3_512_of

Json = dict[str, Any]

_CMP: dict[str, str] = {
    "Eq": "=",
    "NotEq": "≠",
    "Lt": "<",
    "LtE": "≤",
    "Gt": ">",
    "GtE": "≥",
}


@dataclass
class HarvestResult:
    ir: list[Json] = field(default_factory=list)
    call_edges: list[Json] = field(default_factory=list)
    diagnostics: list[Json] = field(default_factory=list)


class _Unsupported(Exception):
    pass


def harvest_source(source: str, source_path: str) -> HarvestResult:
    result = HarvestResult()
    try:
        source_file = SourceFile(
            (source, source_path, blake3_512_of(source.encode("utf-8")))
        )
    except (SyntaxError, BackendCouldNotParse) as exc:
        result.diagnostics.append(
            {
                "kind": "parse-error",
                "message": getattr(exc, "msg", str(exc)),
                "path": source_path,
                "line": getattr(exc, "lineno", None),
            }
        )
        return result

    for node in source_file.root.body:
        if not isinstance(node, FunctionDef):
            continue
        if not node.name.startswith("test_") and not node.name.startswith("test"):
            # Only pytest test functions harvest callsites. (Match `test*`.)
            if not node.name.startswith("test"):
                continue
        atoms: list[Json] = []
        for stmt in node.body:
            if not isinstance(stmt, Assert):
                continue
            try:
                atoms.append(_lift_assert(stmt))
                result.call_edges.extend(
                    _call_edges(stmt, source_path, source_contract=node.name)
                )
            except _Unsupported as exc:
                result.diagnostics.append(
                    {
                        "kind": "leaf-assertion-skipped",
                        "message": str(exc),
                        "path": source_path,
                        "line": stmt.line_col_span().start_line,
                    }
                )
        if not atoms:
            continue
        inv = atoms[0] if len(atoms) == 1 else _and(atoms)
        result.ir.append(
            {
                "schemaVersion": "1",
                "kind": "contract",
                "name": node.name,
                "outBinding": "out",
                "inv": inv,
            }
        )
    return result


def _call_edges(
    stmt: Assert, source_path: str, *, source_contract: str
) -> list[Json]:
    """Project the call coordinates already admitted by ``_lift_assert``.

    This runs only after the assertion translated successfully, so an edge can
    never claim a callsite whose consumer formula the harvester omitted.
    ``targetSymbol`` deliberately uses the ctor's bare name: it is the exact
    EUF coordinate stamped as ``bridgeSourceSymbol`` by ``verify_dialect``.
    """
    edges: list[Json] = []
    for node in stmt.test.walk():
        if not isinstance(node, Call) or not isinstance(node.func, Name):
            continue
        span = node.line_col_span()
        edges.append(
            {
                "kind": "call-edge",
                "sourceContract": source_contract,
                "targetSymbol": node.func.id,
                "callSiteLocus": {
                    "file": source_path,
                    "line": span.start_line,
                    "column": span.start_col,
                },
            }
        )
    return edges


def _lift_assert(stmt: Assert) -> Json:
    test = stmt.test
    if not isinstance(test, Compare):
        raise _Unsupported("assert is not a comparison")
    if len(test.ops) != 1 or len(test.comparators) != 1:
        raise _Unsupported("only single-comparison asserts are harvested")
    lhs = _translate_term(test.left)
    rhs = _translate_term(test.comparators[0])

    if test.ops[0].kind in ("Is", "IsNot"):
        if _is_none_ctor(lhs) == _is_none_ctor(rhs):
            raise _Unsupported("identity comparison is only supported against None")
        op = "=" if test.ops[0].kind == "Is" else "≠"
        return _comparison_with_none_guard(op, lhs, rhs)

    op = _CMP.get(test.ops[0].kind)
    if op is None:
        raise _Unsupported(
            f"comparison op {test.ops[0].kind} not in whitelist"
        )
    return _comparison(op, lhs, rhs)


def _translate_term(node: Expression) -> Json:
    if isinstance(node, Name):
        return {"kind": "var", "name": node.id}
    if isinstance(node, Constant):
        value = node.value
        if isinstance(value, bool):
            return {
                "kind": "const",
                "value": value,
                "sort": {"kind": "primitive", "name": "Bool"},
            }
        if isinstance(value, int):
            return {
                "kind": "const",
                "value": value,
                "sort": {"kind": "primitive", "name": "Int"},
            }
        if isinstance(value, str):
            return {
                "kind": "const",
                "value": value,
                "sort": {"kind": "primitive", "name": "String"},
            }
        if value is None:
            return {"kind": "ctor", "name": "None", "args": []}
        raise _Unsupported(f"unsupported constant {type(value).__name__}")
    if isinstance(node, UnaryOp) and node.op.kind == "USub":
        operand = node.operand
        if (
            isinstance(operand, Constant)
            and isinstance(operand.value, int)
            and not isinstance(operand.value, bool)
        ):
            return {
                "kind": "const",
                "value": -operand.value,
                "sort": {"kind": "primitive", "name": "Int"},
            }
        raise _Unsupported("unary minus only on int literals")
    if isinstance(node, Call):
        # Single-arg bare call f(arg) -> ctor("f", [<arg>]); the ctor name is
        # the bare function symbol the auto-bridge sourceSymbol uses.
        if not isinstance(node.func, Name):
            raise _Unsupported("call callee is not a bare identifier")
        if node.keywords:
            raise _Unsupported("call has keyword arguments")
        args = [_translate_term(arg) for arg in node.args]
        return {"kind": "ctor", "name": node.func.id, "args": args}
    raise _Unsupported(f"operand {type(node).__name__} not supported")


def _and(atoms: list[Json]) -> Json:
    return {"kind": "and", "operands": atoms}


def _comparison(name: str, lhs: Json, rhs: Json) -> Json:
    return {"kind": "atomic", "name": name, "args": [lhs, rhs]}


def _comparison_with_none_guard(name: str, lhs: Json, rhs: Json) -> Json:
    base = _comparison(name, lhs, rhs)
    lhs_is_none = _is_none_ctor(lhs)
    rhs_is_none = _is_none_ctor(rhs)
    if lhs_is_none == rhs_is_none:
        return base

    subject = rhs if lhs_is_none else lhs
    if name == "=":
        return _and([base, {"kind": "atomic", "name": "is_none", "args": [subject]}])
    if name == "≠":
        return _and([base, {"kind": "atomic", "name": "is_some", "args": [subject]}])
    return base


def _is_none_ctor(term: Json) -> bool:
    return (
        term.get("kind") == "ctor"
        and term.get("name") == "None"
        and term.get("args") == []
    )
