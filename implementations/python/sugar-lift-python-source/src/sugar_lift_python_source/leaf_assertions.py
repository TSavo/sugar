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

from .canonical import blake3_512_of, cid_of_json

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


class _LeafCallTestimonyMismatch(TypeError):
    pass


def _construction_refused(kind: str) -> TypeError:
    return TypeError(f"{kind} is producer-minted only")


@dataclass(frozen=True, init=False)
class _CallOccurrence:
    target_symbol: str
    source_cid: str
    source_path: str
    line: int
    column: int
    _call: Call = field(repr=False, compare=False)
    _seal: tuple[object, ...] = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs
        raise _construction_refused("_CallOccurrence")

    @classmethod
    def _mint(cls, call: Call) -> _CallOccurrence:
        if not isinstance(call.func, Name):
            raise _Unsupported("call callee is not a bare identifier")
        span = call.line_col_span()
        self = object.__new__(cls)
        values = (
            call.func.id,
            call.unit.source_cid,
            call.unit.filename,
            span.start_line,
            span.start_col,
        )
        for name, value in zip(
            ("target_symbol", "source_cid", "source_path", "line", "column"),
            values,
            strict=True,
        ):
            object.__setattr__(self, name, value)
        object.__setattr__(self, "_call", call)
        object.__setattr__(self, "_seal", (call, *values))
        return self

    def edge(self, *, source_contract: FunctionDef) -> Json:
        span = self._call.line_col_span()
        observed = (
            self._call,
            self.target_symbol,
            self.source_cid,
            self.source_path,
            self.line,
            self.column,
        )
        if observed != self._seal:
            raise _LeafCallTestimonyMismatch(
                "leaf call testimony does not match its authenticated Call occurrence"
            )
        if (
            not isinstance(self._call.func, Name)
            or self._call.func.id != self.target_symbol
            or self._call.unit.source_cid != self.source_cid
            or self._call.unit.filename != self.source_path
            or span.start_line != self.line
            or span.start_col != self.column
        ):
            raise _LeafCallTestimonyMismatch(
                "leaf call testimony does not match its authenticated Call occurrence"
            )
        contract_span = source_contract.span
        if (
            source_contract.unit is not self._call.unit
            or contract_span.start > self._call.span.start
            or self._call.span.end > contract_span.end
        ):
            raise _LeafCallTestimonyMismatch(
                "leaf call testimony does not belong to the authenticated FunctionDef"
            )
        return {
            "kind": "call-edge",
            "sourceContract": source_contract.name,
            "targetSymbol": self.target_symbol,
            "callSiteLocus": {
                "file": self.source_path,
                "line": self.line,
                "column": self.column,
            },
        }


@dataclass(frozen=True, init=False)
class _TranslatedTerm:
    term: Json
    calls: tuple[_CallOccurrence, ...]
    _preimage: Expression = field(repr=False, compare=False)
    _term_cid: str = field(repr=False, compare=False)
    _seal: tuple[object, ...] = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs
        raise _construction_refused("_TranslatedTerm")

    @classmethod
    def _mint(
        cls,
        *,
        term: Json,
        calls: tuple[_CallOccurrence, ...],
        preimage: Expression,
    ) -> _TranslatedTerm:
        if any(call._call.unit is not preimage.unit for call in calls):
            raise _LeafCallTestimonyMismatch(
                "leaf call roster contains foreign-source testimony"
            )
        self = object.__new__(cls)
        term_cid = cid_of_json(term)
        object.__setattr__(self, "term", term)
        object.__setattr__(self, "calls", calls)
        object.__setattr__(self, "_preimage", preimage)
        object.__setattr__(self, "_term_cid", term_cid)
        object.__setattr__(
            self,
            "_seal",
            (
                preimage,
                preimage.unit.source_cid,
                term_cid,
                tuple(call._seal for call in calls),
            ),
        )
        return self

    def project(self) -> tuple[Json, tuple[_CallOccurrence, ...]]:
        observed = (
            self._preimage,
            self._preimage.unit.source_cid,
            cid_of_json(self.term),
            tuple(call._seal for call in self.calls),
        )
        if observed != self._seal:
            raise _LeafCallTestimonyMismatch(
                "translated term/call roster does not match its authenticated preimage"
            )
        return self.term, self.calls


@dataclass(frozen=True)
class _LiftedAssertion:
    atom: Json
    call_edges: tuple[Json, ...]


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
                lifted = _lift_assert(stmt, source_contract=node)
                atoms.append(lifted.atom)
                result.call_edges.extend(lifted.call_edges)
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


def _lift_assert(stmt: Assert, *, source_contract: FunctionDef) -> _LiftedAssertion:
    test = stmt.test
    if not isinstance(test, Compare):
        raise _Unsupported("assert is not a comparison")
    if len(test.ops) != 1 or len(test.comparators) != 1:
        raise _Unsupported("only single-comparison asserts are harvested")
    lhs = _translate_term(test.left)
    rhs = _translate_term(test.comparators[0])
    lhs_term, lhs_calls = lhs.project()
    rhs_term, rhs_calls = rhs.project()

    if test.ops[0].kind in ("Is", "IsNot"):
        if _is_none_ctor(lhs_term) == _is_none_ctor(rhs_term):
            raise _Unsupported("identity comparison is only supported against None")
        op = "=" if test.ops[0].kind == "Is" else "≠"
        atom = _comparison_with_none_guard(op, lhs_term, rhs_term)
    else:
        op = _CMP.get(test.ops[0].kind)
        if op is None:
            raise _Unsupported(f"comparison op {test.ops[0].kind} not in whitelist")
        atom = _comparison(op, lhs_term, rhs_term)

    calls = lhs_calls + rhs_calls
    return _LiftedAssertion(
        atom=atom,
        call_edges=tuple(
            occurrence.edge(source_contract=source_contract) for occurrence in calls
        ),
    )


def _translate_term(node: Expression) -> _TranslatedTerm:
    if isinstance(node, Name):
        return _TranslatedTerm._mint(
            term={"kind": "var", "name": node.id}, calls=(), preimage=node
        )
    if isinstance(node, Constant):
        value = node.value
        if isinstance(value, bool):
            return _TranslatedTerm._mint(
                term={
                    "kind": "const",
                    "value": value,
                    "sort": {"kind": "primitive", "name": "Bool"},
                },
                calls=(),
                preimage=node,
            )
        if isinstance(value, int):
            return _TranslatedTerm._mint(
                term={
                    "kind": "const",
                    "value": value,
                    "sort": {"kind": "primitive", "name": "Int"},
                },
                calls=(),
                preimage=node,
            )
        if isinstance(value, str):
            return _TranslatedTerm._mint(
                term={
                    "kind": "const",
                    "value": value,
                    "sort": {"kind": "primitive", "name": "String"},
                },
                calls=(),
                preimage=node,
            )
        if value is None:
            return _TranslatedTerm._mint(
                term={"kind": "ctor", "name": "None", "args": []},
                calls=(),
                preimage=node,
            )
        raise _Unsupported(f"unsupported constant {type(value).__name__}")
    if isinstance(node, UnaryOp) and node.op.kind == "USub":
        operand = node.operand
        if (
            isinstance(operand, Constant)
            and isinstance(operand.value, int)
            and not isinstance(operand.value, bool)
        ):
            return _TranslatedTerm._mint(
                term={
                    "kind": "const",
                    "value": -operand.value,
                    "sort": {"kind": "primitive", "name": "Int"},
                },
                calls=(),
                preimage=node,
            )
        raise _Unsupported("unary minus only on int literals")
    if isinstance(node, Call):
        # Single-arg bare call f(arg) -> ctor("f", [<arg>]); the ctor name is
        # the bare function symbol the auto-bridge sourceSymbol uses.
        if not isinstance(node.func, Name):
            raise _Unsupported("call callee is not a bare identifier")
        if node.keywords:
            raise _Unsupported("call has keyword arguments")
        args = [_translate_term(arg) for arg in node.args]
        projected_args = [arg.project() for arg in args]
        occurrence = _CallOccurrence._mint(node)
        return _TranslatedTerm._mint(
            term={
                "kind": "ctor",
                "name": node.func.id,
                "args": [arg.term for arg in args],
            },
            calls=(occurrence,)
            + tuple(call for _, calls in projected_args for call in calls),
            preimage=node,
        )
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
