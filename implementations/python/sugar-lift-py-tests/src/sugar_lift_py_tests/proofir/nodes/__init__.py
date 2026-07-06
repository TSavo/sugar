from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Iterable, Literal, Mapping, NoReturn

from sugar_lift_py_tests.canonicalizer import blake3_512_of, encode_jcs
from sugar_lift_py_tests.factory import (
    FactoryAuditRow,
    FactoryGap,
    FactoryGapInfo,
    GapKind,
    GapLocus,
)
from sugar_lift_py_tests.ir import (
    Formula,
    Int,
    Sort,
    Term,
    _ConstBool,
    _ConstInt,
    _ConstReal,
    _ConstStr,
    _Ctor,
    _Var,
    _json_like_to_value,
    formula_to_value,
)


@dataclass(frozen=True)
class ConstructionSite:
    path: str
    line: int
    column: int = 0

    def to_rpc(self) -> dict[str, Any]:
        return {"path": self.path, "line": self.line, "column": self.column}


@dataclass(frozen=True)
class Stated:
    locus: ConstructionSite

    def to_rpc(self) -> dict[str, Any]:
        return {"kind": "Stated", "locus": self.locus.to_rpc()}


@dataclass(frozen=True)
class Derived:
    floor_chain: tuple[str, ...]

    def to_rpc(self) -> dict[str, Any]:
        return {"kind": "Derived", "floorChain": list(self.floor_chain)}


Warrant = Stated | Derived


@dataclass(frozen=True, init=False)
class Provenance:
    node_class: str
    construction_site: ConstructionSite
    warrants: tuple[Warrant, ...]

    def __init__(
        self,
        *,
        node_class: str,
        construction_site: ConstructionSite,
        warrant: Warrant | Iterable[Warrant],
    ) -> None:
        warrants = _normalize_warrants(warrant)
        if not node_class:
            _proofir_gap(
                owner="Provenance",
                observed="empty node class",
                requested="non-empty node class",
                fix="construct provenance with a ProofIR node class name",
            )
        if not warrants:
            _proofir_gap(
                owner="Provenance",
                observed="empty warrant list",
                requested="at least one Stated or Derived warrant",
                fix="attach the construction warrant before building the node",
            )
        object.__setattr__(self, "node_class", node_class)
        object.__setattr__(self, "construction_site", construction_site)
        object.__setattr__(self, "warrants", warrants)

    def to_rpc(self) -> dict[str, Any]:
        return {
            "nodeClass": self.node_class,
            "constructionSite": self.construction_site.to_rpc(),
            "warrants": [warrant.to_rpc() for warrant in self.warrants],
        }

    def warrant_memento(self) -> dict[str, Any]:
        return {
            "kind": "proofir-provenance",
            **self.to_rpc(),
        }


@dataclass(frozen=True)
class VerdictWitnessCase:
    name: str
    expected: Literal["sat", "unsat", "construction-refusal"]
    formulas: tuple[Formula, ...] = ()
    declarations: Mapping[str, Sort] = field(default_factory=dict)
    construct: Callable[[], object] | None = None
    source: str | None = None
    node_class: str | None = None
    expected_sugar: str | None = None
    refusal_absence: bool = False


@dataclass(frozen=True)
class VerdictWitnessPair:
    truthful: VerdictWitnessCase
    lying: VerdictWitnessCase


class ProofIRNode(ABC):
    node_class: ClassVar[str]

    @abstractmethod
    def denotation(self) -> Formula | None:
        raise NotImplementedError

    @abstractmethod
    def provenance(self) -> Provenance:
        raise NotImplementedError

    @abstractmethod
    def to_declaration(self) -> dict[str, Any]:
        raise NotImplementedError

    def to_proof_ir(self) -> str:
        return encode_jcs(_json_like_to_value(self.to_declaration()))

    def cid(self) -> str:
        return blake3_512_of(self.to_proof_ir().encode("utf-8"))

    def to_semantic_declaration(self) -> dict[str, Any]:
        return self.to_declaration()

    def semantic_cid(self) -> str:
        return _cid_for_declaration(self.to_semantic_declaration())

    @classmethod
    @abstractmethod
    def verdict_witnesses(cls) -> VerdictWitnessPair:
        raise NotImplementedError


_INT_SORT = Int()


def _truthful_source() -> str:
    return (
        "def A(x):\n"
        "    return x + 1\n"
        "\n"
        "def test_a():\n"
        "    assert A(5) == 6\n"
    )


def _lying_source() -> str:
    return (
        "def A(x):\n"
        "    return x + 1\n"
        "\n"
        "def test_a():\n"
        "    assert A(5) == 7\n"
    )


def _normalize_warrants(warrant: Warrant | Iterable[Warrant]) -> tuple[Warrant, ...]:
    if isinstance(warrant, (Stated, Derived)):
        return (warrant,)
    return tuple(warrant)


def _cid_for_declaration(declaration: dict[str, Any]) -> str:
    wire = encode_jcs(_json_like_to_value(declaration))
    return blake3_512_of(wire.encode("utf-8"))


def _merge_provenance(left: Provenance, right: Provenance) -> Provenance:
    if left.node_class != right.node_class:
        _proofir_gap(
            owner="Provenance.merge",
            observed=f"{left.node_class}!={right.node_class}",
            requested="matching ProofIR node classes",
            fix="merge warrants only between nodes of the same vocabulary class",
        )
    return Provenance(
        node_class=left.node_class,
        construction_site=left.construction_site,
        warrant=_union_warrants(left.warrants, right.warrants),
    )


def _union_warrants(
    left: tuple[Warrant, ...], right: tuple[Warrant, ...]
) -> tuple[Warrant, ...]:
    merged: list[Warrant] = []
    seen: set[str] = set()
    for warrant in (*left, *right):
        key = encode_jcs(_json_like_to_value(warrant.to_rpc()))
        if key in seen:
            continue
        seen.add(key)
        merged.append(warrant)
    return tuple(merged)


def _require_provenance(provenance: Provenance, *, owner: str) -> None:
    if not isinstance(provenance, Provenance):
        _proofir_gap(
            owner=owner,
            observed=type(provenance).__name__,
            requested="non-optional Provenance",
            fix="construct the node with Stated or Derived provenance",
        )


def _require_term(term: object, *, owner: str, field_name: str) -> None:
    if not _is_term(term):
        _proofir_gap(
            owner=owner,
            observed=type(term).__name__,
            requested=f"{field_name} must be a typed Term",
            fix="hand the constructor an ir.Term; never a raw dict",
        )


def _is_term(term: object) -> bool:
    return isinstance(term, (_Var, _ConstInt, _ConstStr, _ConstBool, _ConstReal, _Ctor))


def _formula_to_rpc(formula: Formula) -> dict[str, Any]:
    return json.loads(encode_jcs(formula_to_value(formula)))


def _witness_provenance(node_class: str, *, warrants: tuple[str, ...]) -> Provenance:
    site = ConstructionSite(path="proofir/witness.py", line=1, column=0)
    resolved: list[Warrant] = []
    for warrant in warrants:
        if warrant == "Stated":
            resolved.append(Stated(locus=site))
        elif warrant == "Derived":
            resolved.append(Derived(floor_chain=("witness-floor",)))
        else:
            raise AssertionError(f"unknown witness warrant {warrant!r}")
    return Provenance(
        node_class=node_class,
        construction_site=site,
        warrant=tuple(resolved),
    )


def _canonical_term_sig(term: Term) -> str:
    if isinstance(term, _Var):
        return f"v:{term.name}"
    if isinstance(term, _ConstInt):
        return f"i:{term.value}"
    if isinstance(term, _ConstStr):
        return f"s:{term.value!r}"
    if isinstance(term, _ConstBool):
        return f"b:{term.value}"
    if isinstance(term, _ConstReal):
        return f"r:{term.value}"
    if isinstance(term, _Ctor):
        inner = ",".join(_canonical_term_sig(arg) for arg in term.args)
        return f"c:{term.name}({inner})"
    return f"?:{term!r}"


def _proofir_gap(
    *,
    owner: str,
    observed: str,
    requested: str,
    fix: str,
) -> NoReturn:
    info = FactoryGapInfo(
        owner=owner,
        blame="proofir-vocabulary",
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind=GapKind.PROOFIR,
        gap_locus=GapLocus.VOCABULARY,
    )
    raise FactoryGap(
        info,
        FactoryAuditRow(
            role="proofir-vocabulary",
            status="proofir-gap",
            observed=observed,
            blame="proofir-vocabulary",
            selected=None,
            candidates=[],
            message=info.message,
        ),
    )


from .equality_fact import (  # noqa: E402
    EqualityFact,
    canonical_euf_callsite_name,
    merge_equality_facts,
)
from .function_contract import (  # noqa: E402
    Formal,
    FunctionContract,
    FunctionContractBuilder,
)
from .refusal_record import BoundaryRecord, RefusalRecord  # noqa: E402
from .audit_memento import AuditLocus, AuditMemento  # noqa: E402
from .call_edge_decl import BridgeAtom, CallEdgeDecl  # noqa: E402
from .universe_mint import BodyUniverse, UniverseMint  # noqa: E402
from .vendor_conjoin import FactAtom, UniverseAtom, VendorConjoin  # noqa: E402

REGISTERED_PROOFIR_NODE_CLASSES: tuple[type[Any], ...] = (
    EqualityFact,
    FunctionContract,
    BoundaryRecord,
)

_ADDITIONAL_PROOFIR_WITNESS_CLASSES: tuple[type[Any], ...] = (
    CallEdgeDecl,
    AuditMemento,
    UniverseMint,
    VendorConjoin,
)


def registered_verdict_witnesses() -> tuple[tuple[str, bool, bool], ...]:
    registrations: list[tuple[str, bool, bool]] = []
    for node_class in (
        *REGISTERED_PROOFIR_NODE_CLASSES,
        *_ADDITIONAL_PROOFIR_WITNESS_CLASSES,
    ):
        pair = node_class.verdict_witnesses()
        registrations.append(
            (
                node_class.node_class,
                (
                    pair.truthful.expected == "sat"
                    and pair.truthful.source is not None
                    and pair.truthful.expected_sugar is not None
                ),
                (
                    pair.lying.expected == "construction-refusal"
                    or (
                        pair.lying.expected == "unsat"
                        and pair.lying.source is not None
                        and pair.lying.expected_sugar is not None
                    )
                ),
            )
        )
    return tuple(registrations)
