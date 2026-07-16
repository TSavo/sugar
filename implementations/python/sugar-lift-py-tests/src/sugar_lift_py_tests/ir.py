# SPDX-License-Identifier: MIT OR Apache-2.0
#
# Minimal Python IR shape mirroring sugar-ir-symbolic.
#
# Three formula kinds (atomic / connective / quantifier) and three term
# kinds (var / const / ctor). Sort is a primitive name. ContractDecl is
# an emit-time record carrying name, optional pre/post/inv, and an
# outBinding.
#
# Locked IR-JSON shape per protocol/specs/2026-04-30-ir-formal-grammar.md.
# Insertion-order serialization that the canonicalizer's JCS pass re-sorts
# before hashing. We emit canonical Value trees directly (skipping the
# kit's insertion-order JSON string), since downstream hashing is what
# matters.

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import logging
import time
from typing import Any, Iterator, List, Optional, Tuple, Union

from .canonicalizer import (
    Value,
    blake3_512_of,
    encode_jcs,
    jcs_hash,
    varr,
    vbool,
    vint,
    vobj,
    vstr,
    vnull,
)

_TERM_TABLE_LOG = logging.getLogger("sugar.kit.term_table")

# Sort ----------------------------------------------------------------------


@dataclass(frozen=True)
class PrimitiveSort:
    name: str  # "Int" / "Real" / "String" / "Bool"


@dataclass(frozen=True)
class FunctionSort:
    args: Tuple["Sort", ...]
    return_: "Sort"


@dataclass(frozen=True)
class RegionSort:
    def __init__(self, name: str):
        self.name = name

    def kind(self) -> str:
        return "region"


class DependentSort:
    name: str
    index_var: str
    index_sort: "Sort"


Sort = Union[PrimitiveSort, FunctionSort, DependentSort, RegionSort]


def Int() -> Sort:
    return PrimitiveSort("Int")


def Real() -> Sort:
    return PrimitiveSort("Real")


def String() -> Sort:
    return PrimitiveSort("String")


def Bool() -> Sort:
    return PrimitiveSort("Bool")


def FuncOf(args: List[Sort], ret: Sort) -> Sort:
    return FunctionSort(tuple(args), ret)


def Dependent(name: str, index_var: str, index_sort: Sort) -> Sort:
    return DependentSort(name, index_var, index_sort)


# Term ----------------------------------------------------------------------


@dataclass(frozen=True)
class _Var:
    name: str


@dataclass(frozen=True)
class _ConstInt:
    value: int
    sort: Sort


@dataclass(frozen=True)
class _ConstStr:
    value: str
    sort: Sort


@dataclass(frozen=True)
class _ConstBool:
    value: bool
    sort: Sort


@dataclass(frozen=True)
class _ConstReal:
    # The value is a CANONICAL DECIMAL STRING (e.g. "0.0000015"), never a Python
    # float: a float has no deterministic textual form, and this term is hashed
    # into the contract CID. The decimal string is exact and content-addressable;
    # every solver compiler parses it as a real literal of `Real` sort. Tolerances
    # like ``1.5 * 10**(-decimal)`` are exact decimals, so this is lossless.
    value: str
    sort: Sort


@dataclass(frozen=True)
class _Ctor:
    name: str
    args: Tuple["Term", ...]


Term = Union[_Var, _ConstInt, _ConstStr, _ConstBool, _ConstReal, _Ctor]

_TERM_INTERN_TABLE: ContextVar[dict[Term, Term] | None] = ContextVar(
    "sugar_term_intern_table", default=None
)
_CONSTRUCTOR_SYMBOL_KINDS: ContextVar[dict[str, str] | None] = ContextVar(
    "sugar_constructor_symbol_kinds", default=None
)


@contextmanager
def term_intern_scope() -> Iterator[None]:
    intern_token = _TERM_INTERN_TABLE.set({})
    symbols_token = _CONSTRUCTOR_SYMBOL_KINDS.set({})
    try:
        yield
    finally:
        _CONSTRUCTOR_SYMBOL_KINDS.reset(symbols_token)
        _TERM_INTERN_TABLE.reset(intern_token)


def _intern_term(term: Term) -> Term:
    table = _TERM_INTERN_TABLE.get()
    if table is None:
        return term
    return table.setdefault(term, term)


def make_var(name: str) -> Term:
    return _intern_term(_Var(name))


def num(n: int) -> Term:
    return _intern_term(_ConstInt(int(n), Int()))


def str_const(s: str) -> Term:
    return _intern_term(_ConstStr(s, String()))


def real_lit(decimal_string: str) -> Term:
    """A real literal carried as a canonical decimal string (e.g. "0.0000015").

    NEVER pass a Python float: the value is hashed into the contract CID and a
    float has no deterministic text form. Build the string exactly (e.g. with
    ``decimal.Decimal``) so every solver compiler reads the same literal."""
    return _intern_term(_ConstReal(decimal_string, Real()))


def bool_const(b: bool) -> Term:
    return _intern_term(_ConstBool(bool(b), Bool()))


_SYMBOL_KINDS = frozenset(
    {"coordinate", "builtin", "contract-target", "method-coordinate"}
)
_EMITTER_OWNED_SYMBOL_KINDS = {
    "None": "coordinate",
    "array": "coordinate",
    "kw": "coordinate",
    "python:builtin": "coordinate",
    "python:dict": "coordinate",
    "python:dict_entry": "coordinate",
    "python:function": "coordinate",
    "python:type": "coordinate",
    "tuple": "coordinate",
}


def ctor(name: str, args: List[Term], *, symbol_kind: Optional[str] = None) -> Term:
    if symbol_kind is None:
        symbol_kind = _EMITTER_OWNED_SYMBOL_KINDS.get(name)
    if symbol_kind is not None and symbol_kind not in _SYMBOL_KINDS:
        raise ValueError(f"unknown constructor symbol kind: {symbol_kind}")
    if symbol_kind is not None:
        symbol_kinds = _CONSTRUCTOR_SYMBOL_KINDS.get()
        if symbol_kinds is not None:
            merge_constructor_symbol_kind(symbol_kinds, name, symbol_kind)
    return _intern_term(_Ctor(name, tuple(args)))


def constructor_symbol_kinds() -> dict[str, str]:
    return dict(_CONSTRUCTOR_SYMBOL_KINDS.get() or {})


def merge_constructor_symbol_kind(
    symbol_kinds: dict[str, str], symbol: str, kind: str
) -> None:
    prior = symbol_kinds.get(symbol)
    if prior is None or prior == kind:
        symbol_kinds[symbol] = kind
        return
    refinable = {"coordinate", "method-coordinate", "contract-target"}
    if prior in refinable and kind in refinable:
        if "contract-target" in {prior, kind}:
            symbol_kinds[symbol] = "contract-target"
        elif "method-coordinate" in {prior, kind}:
            symbol_kinds[symbol] = "method-coordinate"
        return
    if "builtin" in {prior, kind} and {prior, kind} <= _SYMBOL_KINDS:
        # A canonical ``call:name`` head can be reached both as a seeded
        # builtin and as an attribute/method coordinate with the same spelling.
        # The sidecar is presentation testimony only; their truthful common
        # classification is the generic coordinate, while the term and CID
        # remain unchanged.
        symbol_kinds[symbol] = "coordinate"
        return
    raise ValueError(
        f"constructor {symbol!r} has conflicting symbol kinds: {prior!r} and {kind!r}"
    )


def bvand(left: Term, right: Term) -> Term:
    return ctor("bv32.and", [left, right])


def bvor(left: Term, right: Term) -> Term:
    return ctor("bv32.or", [left, right])


def bvxor(left: Term, right: Term) -> Term:
    return ctor("bv32.xor", [left, right])


def bvshl(left: Term, right: Term) -> Term:
    return ctor("bv32.shl", [left, right])


def bvlshr(left: Term, right: Term) -> Term:
    return ctor("bv32.lshr", [left, right])


def bvadd(left: Term, right: Term) -> Term:
    return ctor("bv32.add", [left, right])


# Formula -------------------------------------------------------------------


@dataclass(frozen=True)
class _Atomic:
    name: str
    args: Tuple[Term, ...]


@dataclass(frozen=True)
class _Connective:
    kind: str  # and / or / not / implies
    operands: Tuple["Formula", ...]


@dataclass(frozen=True)
class _Quantifier:
    kind: str  # forall / exists
    name: str
    sort: Sort
    body: "Formula"


Formula = Union[_Atomic, _Connective, _Quantifier]


def atomic(name: str, args: List[Term]) -> Formula:
    return _Atomic(name, tuple(args))


# Atomic predicate names use the Unicode glyphs >=, <=, !=. Cross-language
# hash agreement depends on UTF-8 verbatim emission for U+0080+.
def gt(a: Term, b: Term) -> Formula:
    return atomic(">", [a, b])


def gte(a: Term, b: Term) -> Formula:
    return atomic("≥", [a, b])


def lt(a: Term, b: Term) -> Formula:
    return atomic("<", [a, b])


def lte(a: Term, b: Term) -> Formula:
    return atomic("≤", [a, b])


def eq(a: Term, b: Term) -> Formula:
    return atomic("=", [a, b])


def py_eq(a: Term, b: Term) -> Formula:
    """Python `==` as an operator-indexed atom; the sort universe adjudicates (NaN: py.eq is not reflexive on floats)."""
    return atomic("py.eq", [a, b])


def py_lt(a: Term, b: Term) -> Formula:
    """Python `<` as an operator-indexed atom; the sort universe adjudicates (NaN: IEEE ordering is not total on floats)."""
    return atomic("py.lt", [a, b])


def py_le(a: Term, b: Term) -> Formula:
    """Python `<=` as an operator-indexed atom; the sort universe adjudicates (the operator is faithful to `__le__`)."""
    return atomic("py.le", [a, b])


def py_gt(a: Term, b: Term) -> Formula:
    """Python `>` as an operator-indexed atom; the sort universe adjudicates (the operator is faithful to `__gt__`)."""
    return atomic("py.gt", [a, b])


def py_ge(a: Term, b: Term) -> Formula:
    """Python `>=` as an operator-indexed atom; the sort universe adjudicates (the operator is faithful to `__ge__`)."""
    return atomic("py.ge", [a, b])


def py_truthy(a: Term) -> Formula:
    """The Python truth relation as an atom; the sort adjudicates the interpretation."""
    return atomic("py.truthy", [a])


def py_raises(exc: Term) -> Formula:
    """Testimony: pytest.raises(exc) / with-raises pattern stated as inv."""
    return atomic("pytest.raises", [exc])


def identity(a: Term, b: Term) -> Formula:
    return atomic("identity", [a, b])


def ne(a: Term, b: Term) -> Formula:
    return atomic("≠", [a, b])


def comparison_with_none_guard(
    name: str, left: Term, right: Term, *, emit_none_guard: bool = True
) -> Formula:
    base = atomic(name, [left, right])
    if not emit_none_guard:
        return base
    left_is_none = _is_none_ctor(left)
    right_is_none = _is_none_ctor(right)
    if left_is_none == right_is_none:
        return base
    subject = right if left_is_none else left
    if name == "=":
        return and_([base, atomic("is_none", [subject])])
    if name == "≠":
        return and_([base, atomic("is_some", [subject])])
    return base


def _is_none_ctor(term: Term) -> bool:
    return isinstance(term, _Ctor) and term.name == "None" and not term.args


def connective(kind: str, operands: List[Formula]) -> Formula:
    return _Connective(kind, tuple(operands))


def not_(a: Formula) -> Formula:
    return connective("not", [a])


def implies(a: Formula, b: Formula) -> Formula:
    return connective("implies", [a, b])


def and_(operands: List[Formula]) -> Formula:
    return connective("and", operands)


def or_(operands: List[Formula]) -> Formula:
    return connective("or", operands)


def forall(name: str, sort: Sort, body: Formula) -> Formula:
    return _Quantifier("forall", name, sort, body)


def exists(name: str, sort: Sort, body: Formula) -> Formula:
    return _Quantifier("exists", name, sort, body)


def formula_term(formula: Formula) -> Term:
    """Reify an existing formula as a coordinate for conditional terms."""
    if isinstance(formula, _Atomic):
        return ctor(
            f"formula:{formula.name}",
            list(formula.args),
            symbol_kind="coordinate",
        )
    if isinstance(formula, _Connective):
        return ctor(
            f"formula:{formula.kind}",
            [formula_term(operand) for operand in formula.operands],
            symbol_kind="coordinate",
        )
    if isinstance(formula, _Quantifier):
        sort_name = getattr(formula.sort, "name", type(formula.sort).__name__)
        return ctor(
            f"formula:{formula.kind}",
            [str_const(formula.name), str_const(sort_name), formula_term(formula.body)],
            symbol_kind="coordinate",
        )
    raise TypeError(f"unknown Formula construction: {type(formula).__name__}")


# EvidenceTerm --------------------------------------------------------------
#
# Mirrors implementations/rust/sugar-ir-symbolic/src/lib.rs (EvidenceTerm
# / EvidenceCertificate) and the spec at
# protocol/specs/2026-04-30-ir-formal-grammar.md (EvidenceTerm grammar).
#
# Locked key orders (canonicalizer's JCS pass re-sorts to alphabetical
# before hashing; insertion order recorded here mirrors Rust's
# Value::object call order in serialize.rs):
#   evidence:    {kind: "evidence", proofType, certificate}
#   certificate: {tool, version, formulaHash, proofData}
#
# proofType is one of "smt-lib" | "coq" | "custom".


@dataclass(frozen=True)
class EvidenceCertificate:
    tool: str
    version: str
    formula_hash: str
    proof_data: str


@dataclass(frozen=True)
class EvidenceTerm:
    proof_type: str  # "smt-lib" | "coq" | "custom"
    certificate: EvidenceCertificate


def evidence_to_value(e: EvidenceTerm) -> Value:
    return vobj(
        [
            ("kind", vstr("evidence")),
            ("proofType", vstr(e.proof_type)),
            (
                "certificate",
                vobj(
                    [
                        ("tool", vstr(e.certificate.tool)),
                        ("version", vstr(e.certificate.version)),
                        ("formulaHash", vstr(e.certificate.formula_hash)),
                        ("proofData", vstr(e.certificate.proof_data)),
                    ]
                ),
            ),
        ]
    )


# ContractDecl --------------------------------------------------------------


@dataclass
class ContractDecl:
    name: str
    pre: Optional[Formula] = None
    post: Optional[Formula] = None
    inv: Optional[Formula] = None
    out_binding: str = "out"
    evidence: Optional[EvidenceTerm] = None
    source_warrants: List[dict[str, Any]] = field(default_factory=list)


# To-Value (canonicalizer Value tree) --------------------------------------


def sort_to_value(s: Sort) -> Value:
    if isinstance(s, PrimitiveSort):
        return vobj([("kind", vstr("primitive")), ("name", vstr(s.name))])
    if isinstance(s, FunctionSort):
        return vobj(
            [
                ("kind", vstr("function")),
                ("args", varr([sort_to_value(a) for a in s.args])),
                ("return", sort_to_value(s.return_)),
            ]
        )
    if isinstance(s, DependentSort):
        return vobj(
            [
                ("kind", vstr("dependent")),
                ("name", vstr(s.name)),
                ("indexVar", vstr(s.index_var)),
                ("indexSort", sort_to_value(s.index_sort)),
            ]
        )
    if isinstance(s, RegionSort):
        return vobj([("kind", vstr("region")), ("name", vstr(s.name))])

    raise TypeError(f"Unknown sort: {s!r}")


def term_to_value(t: Term) -> Value:
    if isinstance(t, _Var):
        return vobj([("kind", vstr("var")), ("name", vstr(t.name))])
    if isinstance(t, _ConstInt):
        return vobj(
            [
                ("kind", vstr("const")),
                ("value", vint(t.value)),
                ("sort", sort_to_value(t.sort)),
            ]
        )
    if isinstance(t, _ConstStr):
        return vobj(
            [
                ("kind", vstr("const")),
                ("value", vstr(t.value)),
                ("sort", sort_to_value(t.sort)),
            ]
        )
    if isinstance(t, _ConstBool):
        from .canonicalizer import vbool

        return vobj(
            [
                ("kind", vstr("const")),
                ("value", vbool(t.value)),
                ("sort", sort_to_value(t.sort)),
            ]
        )
    if isinstance(t, _ConstReal):
        # The real value rides as a STRING (canonical decimal) so the CID is
        # deterministic. Discriminated from a string literal by its `Real` sort:
        # every compiler dispatches on sort to parse it as a real literal.
        return vobj(
            [
                ("kind", vstr("const")),
                ("value", vstr(t.value)),
                ("sort", sort_to_value(t.sort)),
            ]
        )
    if isinstance(t, _Ctor):
        return vobj(
            [
                ("kind", vstr("ctor")),
                ("name", vstr(t.name)),
                ("args", varr([term_to_value(a) for a in t.args])),
            ]
        )
    raise TypeError(f"unknown Term: {type(t)!r}")


class TermTableBuilder:
    """One-way JSON-RPC lowering of immutable terms into a CID-keyed DAG."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        # Identity-keyed so looking up a deep frozen dataclass never invokes its
        # recursively generated __hash__. The retained term guards against id
        # reuse while this builder is alive.
        self._cids: dict[int, tuple[Term, str]] = {}

    def reference(self, term: Term) -> dict[str, str]:
        cid = self._cached_cid(term)
        if cid is not None and cid in self.nodes:
            self._log_node(term, cid, cache="hit")
            return {"kind": "term-ref", "cid": cid}

        self._materialize(term)
        cid = self._require_cached_cid(term)
        return {"kind": "term-ref", "cid": cid}

    def formula(self, formula: Formula) -> dict[str, Any]:
        if isinstance(formula, _Atomic):
            return {
                "kind": "atomic",
                "name": formula.name,
                "args": [self.reference(term) for term in formula.args],
            }
        if isinstance(formula, _Connective):
            return {
                "kind": formula.kind,
                "operands": [self.formula(operand) for operand in formula.operands],
            }
        if isinstance(formula, _Quantifier):
            return {
                "kind": formula.kind,
                "name": formula.name,
                "sort": json.loads(encode_jcs(sort_to_value(formula.sort))),
                "body": self.formula(formula.body),
            }
        raise TypeError(f"unknown Formula: {type(formula)!r}")

    def formula_rpc(self, formula: dict[str, Any]) -> dict[str, Any]:
        """Lower an already-typed source-lifter formula through this table.

        The source lifter owns a distinct typed IR package whose membrane is
        its RPC value.  Importing one of its contracts into the combined lift
        payload must still route every term through the payload's one DAG
        writer instead of embedding the source-lifter tree.
        """
        kind = formula.get("kind")
        if kind == "atomic":
            return {
                "kind": "atomic",
                "name": formula["name"],
                "args": [self.reference_rpc(term) for term in formula.get("args", [])],
            }
        if kind in {"and", "or", "not", "implies"}:
            return {
                "kind": kind,
                "operands": [
                    self.formula_rpc(operand) for operand in formula.get("operands", [])
                ],
            }
        if kind in {"forall", "exists"}:
            return {
                "kind": kind,
                "name": formula["name"],
                "sort": formula["sort"],
                "body": self.formula_rpc(formula["body"]),
            }
        raise TypeError(f"unknown source-lifter formula kind: {kind!r}")

    def reference_rpc(self, term: dict[str, Any]) -> dict[str, str]:
        """Intern one source-lifter RPC term under its canonical CID.

        Heap-backed postorder walk — same depth law as typed ``reference`` /
        ``_materialize``. Native recursion here is the encode-side twin of the
        typed stack overflow (#4573 residual): a deep ctor spine must not
        depend on CPython's call stack for either CID minting or child interning.
        """
        cid = self._materialize_rpc(term)
        return {"kind": "term-ref", "cid": cid}

    def _materialize_rpc(self, root: dict[str, Any]) -> str:
        """Intern one JSON-RPC term tree without native recursion.

        Expanded-term canonical bytes (the CID preimage) are built bottom-up on
        an explicit worklist. Table rows still store child ``term-ref`` edges so
        the wire remains a DAG. Object-identity memo within one walk dedups
        shared dicts; cross-call dedup remains CID-keyed via ``self.nodes``.
        """
        if not isinstance(root, dict):
            raise TypeError(
                f"reference_rpc expects a term dict, got {type(root)!r}; "
                "fix=pass source-lifter RPC term objects only"
            )

        # Expanded canonical retained only for shared objects (inbound > 1).
        inbound: dict[int, int] = {}
        seen: set[int] = set()
        pending: list[dict[str, Any]] = [root]
        while pending:
            term = pending.pop()
            identity = id(term)
            if identity in seen:
                continue
            if not isinstance(term, dict):
                raise TypeError(
                    f"RPC term child must be a dict, got {type(term)!r}; "
                    "fix=source-lifter terms are JSON objects only"
                )
            seen.add(identity)
            if term.get("kind") == "ctor":
                for child in term.get("args", []) or []:
                    if not isinstance(child, dict):
                        raise TypeError(
                            f"RPC ctor arg must be a dict, got {type(child)!r}"
                        )
                    child_id = id(child)
                    inbound[child_id] = inbound.get(child_id, 0) + 1
                    pending.append(child)

        shared_canonical: dict[int, str] = {}
        cid_by_id: dict[int, str] = {}
        values: list[str] = []
        work: list[tuple[dict[str, Any], bool]] = [(root, False)]
        while work:
            term, finishing = work.pop()
            identity = id(term)
            cached_value = shared_canonical.get(identity)
            if not finishing and cached_value is not None:
                values.append(cached_value)
                continue
            if term.get("kind") == "ctor" and not finishing:
                work.append((term, True))
                args = term.get("args", []) or []
                work.extend((child, False) for child in reversed(args))
                continue

            if term.get("kind") == "ctor":
                args = term.get("args", []) or []
                arity = len(args)
                children = values[-arity:] if arity else []
                if arity:
                    del values[-arity:]
                canonical = (
                    '{"args":['
                    + ",".join(children)
                    + '],"kind":"ctor","name":'
                    + encode_jcs(vstr(term["name"]))
                    + "}"
                )
                node_payload: dict[str, Any] = {
                    "kind": "ctor",
                    "name": term["name"],
                    "args": [
                        {
                            "kind": "term-ref",
                            "cid": blake3_512_of(child.encode("utf-8")),
                        }
                        for child in children
                    ],
                }
            else:
                # Leaves are shallow JSON objects — encode_jcs over the value
                # tree is O(leaf size), not O(spine depth).
                canonical = encode_jcs(_json_like_to_value(term))
                node_payload = json.loads(canonical)

            cid = blake3_512_of(canonical.encode("utf-8"))
            cid_by_id[identity] = cid
            if inbound.get(identity, 0) > 1:
                shared_canonical[identity] = canonical
            if cid not in self.nodes:
                self.nodes[cid] = node_payload
                node_count = len(self.nodes)
                if node_count % 1000 == 0:
                    _TERM_TABLE_LOG.info(
                        "term_table_progress",
                        extra={
                            "stage": "lift.workspace.to_rpc.term_table.progress",
                            "unique_nodes": node_count,
                            "door": "reference_rpc",
                        },
                    )
            values.append(canonical)

        if len(values) != 1:
            raise AssertionError(
                f"iterative RPC term encoder left {len(values)} canonical values"
            )
        root_cid = cid_by_id.get(id(root))
        if root_cid is None:
            raise AssertionError("iterative RPC term encoder lost the root CID")
        return root_cid

    def _cid(self, term: Term) -> str:
        cid = self._cached_cid(term)
        if cid is None:
            self._materialize(term)
            cid = self._require_cached_cid(term)
        return cid

    def _node(self, term: Term) -> dict[str, Any]:
        if isinstance(term, _Ctor):
            return {
                "kind": "ctor",
                "name": term.name,
                "args": [
                    {"kind": "term-ref", "cid": self._require_cached_cid(arg)}
                    for arg in term.args
                ],
            }
        return json.loads(encode_jcs(term_to_value(term)))

    def _materialize(self, root: Term) -> None:
        """Intern one expanded term tree with heap-backed postorder traversal."""
        inbound: dict[int, int] = {}
        seen: set[int] = set()
        pending = [root]
        while pending:
            term = pending.pop()
            identity = id(term)
            if identity in seen:
                continue
            seen.add(identity)
            if isinstance(term, _Ctor):
                for child in term.args:
                    child_id = id(child)
                    inbound[child_id] = inbound.get(child_id, 0) + 1
                    pending.append(child)

        # Canonical strings are retained only for shared nodes. A linear spine
        # therefore uses O(depth + root-bytes) memory instead of retaining every
        # expanded prefix, while repeated DAG children are serialized once.
        shared_canonical: dict[int, str] = {}
        values: list[str] = []
        work: list[tuple[Term, bool]] = [(root, False)]
        while work:
            term, finishing = work.pop()
            identity = id(term)
            cached_value = shared_canonical.get(identity)
            if not finishing and cached_value is not None:
                values.append(cached_value)
                continue
            if isinstance(term, _Ctor) and not finishing:
                work.append((term, True))
                work.extend((child, False) for child in reversed(term.args))
                continue

            if isinstance(term, _Ctor):
                arity = len(term.args)
                children = values[-arity:] if arity else []
                if arity:
                    del values[-arity:]
                canonical = (
                    '{"args":['
                    + ",".join(children)
                    + '],"kind":"ctor","name":'
                    + encode_jcs(vstr(term.name))
                    + "}"
                )
            else:
                canonical = encode_jcs(term_to_value(term))

            if inbound.get(identity, 0) > 1:
                shared_canonical[identity] = canonical
            self._record_node(term, canonical)
            values.append(canonical)

        if len(values) != 1:
            raise AssertionError(
                f"iterative term encoder left {len(values)} canonical values"
            )

    def _record_node(self, term: Term, canonical: str) -> None:
        started = time.monotonic()
        cid = self._cached_cid(term)
        if cid is None:
            cid = blake3_512_of(canonical.encode("utf-8"))
            self._cids[id(term)] = (term, cid)
            if _TERM_TABLE_LOG.isEnabledFor(logging.DEBUG):
                _TERM_TABLE_LOG.debug(
                    "term_cid_minted",
                    extra={
                        "stage": "lift.workspace.to_rpc.term_table.cid",
                        "cid": cid,
                        "cid_count": len(self._cids),
                        "term_kind": type(term).__name__,
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                    },
                )
        if cid in self.nodes:
            self._log_node(term, cid, cache="hit")
            return
        self.nodes[cid] = self._node(term)
        self._log_node(term, cid, cache="miss")
        node_count = len(self.nodes)
        if node_count % 1000 == 0:
            _TERM_TABLE_LOG.info(
                "term_table_progress",
                extra={
                    "stage": "lift.workspace.to_rpc.term_table.progress",
                    "unique_nodes": node_count,
                },
            )

    def _cached_cid(self, term: Term) -> str | None:
        entry = self._cids.get(id(term))
        if entry is not None and entry[0] is term:
            return entry[1]
        return None

    def _require_cached_cid(self, term: Term) -> str:
        cid = self._cached_cid(term)
        if cid is None:
            raise AssertionError(
                f"term child reached node emission before CID mint: {type(term).__name__}"
            )
        return cid

    def _log_node(self, term: Term, cid: str, *, cache: str) -> None:
        if _TERM_TABLE_LOG.isEnabledFor(logging.DEBUG):
            _TERM_TABLE_LOG.debug(
                "term_table_node",
                extra={
                    "stage": "lift.workspace.to_rpc.term_table.node",
                    "cid": cid,
                    "node_count": len(self.nodes),
                    "cache": cache,
                    "term_kind": type(term).__name__,
                },
            )


def formula_to_value(f: Formula) -> Value:
    if isinstance(f, _Atomic):
        return vobj(
            [
                ("kind", vstr("atomic")),
                ("name", vstr(f.name)),
                ("args", varr([term_to_value(a) for a in f.args])),
            ]
        )
    if isinstance(f, _Connective):
        return vobj(
            [
                ("kind", vstr(f.kind)),
                ("operands", varr([formula_to_value(o) for o in f.operands])),
            ]
        )
    if isinstance(f, _Quantifier):
        return vobj(
            [
                ("kind", vstr(f.kind)),
                ("name", vstr(f.name)),
                ("sort", sort_to_value(f.sort)),
                ("body", formula_to_value(f.body)),
            ]
        )
    raise TypeError(f"unknown Formula: {type(f)!r}")


# Variable substitution (used by helper-inlining and parametrize patterns)


def subst_var_in_term(t: Term, formal: str, actual: Term) -> Term:
    if isinstance(t, _Var):
        return actual if t.name == formal else t
    if isinstance(t, _Ctor):
        return ctor(t.name, [subst_var_in_term(a, formal, actual) for a in t.args])
    return t  # const variants are inert


def subst_var_in_formula(f: Formula, formal: str, actual: Term) -> Formula:
    if isinstance(f, _Atomic):
        return _Atomic(
            f.name, tuple(subst_var_in_term(a, formal, actual) for a in f.args)
        )
    if isinstance(f, _Connective):
        return _Connective(
            f.kind, tuple(subst_var_in_formula(o, formal, actual) for o in f.operands)
        )
    if isinstance(f, _Quantifier):
        # Don't substitute under a shadowing binder.
        if f.name == formal:
            return f
        return _Quantifier(
            f.kind, f.name, f.sort, subst_var_in_formula(f.body, formal, actual)
        )
    raise TypeError(f"unknown Formula: {type(f)!r}")


# BridgeDecl ----------------------------------------------------------------
#
# Cross-bundle bridge declaration per
# protocol/specs/2026-04-30-ir-formal-grammar.md §BridgeDeclaration. The
# shape mirrors `sugar-ir-types::Declaration::Bridge` (the codegen-derived
# Rust struct) and the TS `BridgeSpec` shape. The `sourceContractCid` +
# `targetProofCid` fields make cross-bundle witness pinning hash-bounded
# (no implicit lookup): the verifier loads the named target proof bundle
# by CID and checks the contract inside it.
#
# Locked key order (per spec line 274-275):
#   kind, name, sourceSymbol, sourceLayer, sourceContractCid,
#   targetContractCid, targetProofCid, targetLayer, [notes?]
#
# `notes` is OMITTED entirely when None (never emitted as null). This is
# the byte-equality rule that keeps the four kits in sync (spec line
# 347-350).


@dataclass(frozen=True)
class BridgeDecl:
    name: str
    source_symbol: str
    source_layer: str
    source_contract_cid: str
    target_contract_cid: str
    target_proof_cid: str
    target_layer: str
    notes: Optional[str] = None


def bridge_decl_to_value(b: BridgeDecl) -> Value:
    pairs: List[Tuple[str, Value]] = [
        ("kind", vstr("bridge")),
        ("name", vstr(b.name)),
        ("sourceSymbol", vstr(b.source_symbol)),
        ("sourceLayer", vstr(b.source_layer)),
        ("sourceContractCid", vstr(b.source_contract_cid)),
        ("targetContractCid", vstr(b.target_contract_cid)),
        ("targetProofCid", vstr(b.target_proof_cid)),
        ("targetLayer", vstr(b.target_layer)),
    ]
    if b.notes is not None:
        pairs.append(("notes", vstr(b.notes)))
    return vobj(pairs)


def contract_decl_to_value(d: ContractDecl) -> Value:
    """Emit a contract declaration as a canonicalizer Value.

    Mirrors the Rust `marshal_declarations` shape, but as a Value tree so
    the JCS pass produces byte-equal output to Rust's value-tree path.
    Locked key order: kind, name, outBinding, [pre?], [post?], [inv?],
    [evidence?], [sourceWarrants?].
    """
    pairs: List[Tuple[str, Value]] = [
        ("kind", vstr("contract")),
        ("name", vstr(d.name)),
        ("outBinding", vstr(d.out_binding)),
    ]
    if d.pre is not None:
        pairs.append(("pre", formula_to_value(d.pre)))
    if d.post is not None:
        pairs.append(("post", formula_to_value(d.post)))
    if d.inv is not None:
        pairs.append(("inv", formula_to_value(d.inv)))
    if d.evidence is not None:
        pairs.append(("evidence", evidence_to_value(d.evidence)))
    if d.source_warrants:
        pairs.append(
            (
                "sourceWarrants",
                varr([_json_like_to_value(warrant) for warrant in d.source_warrants]),
            )
        )
    return vobj(pairs)


def _json_like_to_value(value: Any) -> Value:
    if value is None:
        return vnull()
    if isinstance(value, bool):
        return vbool(value)
    if isinstance(value, int):
        return vint(value)
    if isinstance(value, str):
        return vstr(value)
    if isinstance(value, list):
        return varr([_json_like_to_value(item) for item in value])
    if isinstance(value, tuple):
        return varr([_json_like_to_value(item) for item in value])
    if isinstance(value, dict):
        return vobj([(str(k), _json_like_to_value(v)) for k, v in value.items()])
    raise TypeError(f"unsupported source warrant JSON value: {type(value)!r}")


def declarations_to_value(
    decls: List[Union[ContractDecl, BridgeDecl]],
) -> Value:
    """Emit a mixed list of contract/bridge declarations as a Value array.

    Matches Rust's `marshal_declarations` (insertion-order JSON in Rust;
    canonicalizer's JCS pass re-sorts keys before hashing).
    """
    items: List[Value] = []
    for d in decls:
        if isinstance(d, ContractDecl):
            items.append(contract_decl_to_value(d))
        elif isinstance(d, BridgeDecl):
            items.append(bridge_decl_to_value(d))
        else:
            raise TypeError(f"unknown declaration: {type(d)!r}")
    return varr(items)


# Locus -----------------------------------------------------------------------
#
# Source position for a call site.
# JSON shape (JCS-canonical key order: column, file, line).
# Mirrors Go's Locus struct (property.go lines 267-293).


@dataclass(frozen=True)
class Locus:
    file: str
    line: int
    column: int


def locus_to_value(loc: Locus) -> Value:
    """Emit Locus as a Value with JCS-canonical key order: column, file, line."""
    return vobj(
        [
            ("column", vint(loc.column)),
            ("file", vstr(loc.file)),
            ("line", vint(loc.line)),
        ]
    )


# CallEdgeDecl ----------------------------------------------------------------
#
# Call-edge memento per protocol/specs/2026-05-03-bridge-linkage-protocol.md §1.
# JSON shape (JCS-canonical key order: callSiteLocus, evidenceTerm, kind,
# schemaVersion, sourceContractCid, targetContractCid, targetSymbol).
# Mirrors Go's CallEdgeDeclaration.MarshalJSON (property.go lines 331-368).
#
# targetContractCid is None for cross-kit calls (encodes as JSON null).
# targetSymbol carries the kit-prefixed name, e.g. "rust-kit:foo".


@dataclass(frozen=True)
class CallEdgeDecl:
    source_contract_cid: str
    target_contract_cid: Optional[str]  # None -> JSON null
    target_symbol: str
    call_site_locus: Locus
    evidence_term: Formula


def call_edge_decl_to_value(c: CallEdgeDecl) -> Value:
    """Emit a call-edge declaration as a canonicalizer Value.

    JCS-canonical key order: callSiteLocus, evidenceTerm, kind, schemaVersion,
    sourceContractCid, targetContractCid, targetSymbol.
    """
    target_cid_value: Value = (
        vnull() if c.target_contract_cid is None else vstr(c.target_contract_cid)
    )
    return vobj(
        [
            ("callSiteLocus", locus_to_value(c.call_site_locus)),
            ("evidenceTerm", formula_to_value(c.evidence_term)),
            ("kind", vstr("call-edge")),
            ("schemaVersion", vstr("1")),
            ("sourceContractCid", vstr(c.source_contract_cid)),
            ("targetContractCid", target_cid_value),
            ("targetSymbol", vstr(c.target_symbol)),
        ]
    )


def call_edges_to_value(edges: List["CallEdgeDecl"]) -> Value:
    """Emit a list of call-edge declarations as a Value array."""
    return varr([call_edge_decl_to_value(e) for e in edges])
