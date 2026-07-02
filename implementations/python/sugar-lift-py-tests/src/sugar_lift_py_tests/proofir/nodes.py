from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import InitVar, dataclass, field
from typing import Any, Callable, ClassVar, Iterable, Literal, Mapping

from sugar_lift_py_tests.canonicalizer import blake3_512_of, encode_jcs
from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.factory.dig_refusal import DigRefusal
from sugar_lift_py_tests.ir import (
    Formula,
    Sort,
    Term,
    _Atomic,
    _Connective,
    _ConstBool,
    _ConstInt,
    _ConstReal,
    _ConstStr,
    _Ctor,
    _Quantifier,
    _Var,
    _json_like_to_value,
    ctor,
    eq,
    formula_to_value,
    forall,
    implies,
    make_var,
    num,
)
from sugar_lift_py_tests.kit_rpc import BodyUniverseDto
from sugar_lift_py_tests.outcome import Incomplete


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


@dataclass(frozen=True)
class EqualityFact(ProofIRNode):
    node_class: ClassVar[str] = "EqualityFact"

    euf_key: str
    call_term: Term
    rhs_term: Term
    provenance: InitVar[Provenance]
    _provenance: Provenance = field(init=False, repr=False)

    def __post_init__(self, provenance: Provenance) -> None:
        _require_provenance(provenance, owner=self.node_class)
        _require_term(self.call_term, owner=self.node_class, field_name="call_term")
        _require_term(self.rhs_term, owner=self.node_class, field_name="rhs_term")
        if not isinstance(self.call_term, _Ctor) or not self.call_term.name.startswith("call:"):
            _proofir_gap(
                owner=self.node_class,
                observed=repr(self.call_term),
                requested="call_term with a call:<callee> ctor head",
                fix="construct EqualityFact from euf_call_term(callee, args)",
            )
        expected_key = canonical_euf_callsite_name(self.call_term)
        if self.euf_key != expected_key:
            _proofir_gap(
                owner=self.node_class,
                observed=f"euf_key={self.euf_key!r}",
                requested=f"euf_key={expected_key!r}",
                fix="derive the key from the call term with the canonical #euf# speller",
            )
        object.__setattr__(self, "_provenance", provenance)

    def denotation(self) -> Formula:
        return eq(self.call_term, self.rhs_term)

    def provenance(self) -> Provenance:
        return self._provenance

    def to_declaration(self) -> dict[str, Any]:
        return BodyUniverseDto(
            name=self.euf_key,
            out_binding="out",
            inv=_formula_to_rpc(self.denotation()),
            source_warrants=[self.provenance().warrant_memento()],
        ).to_rpc()

    def to_semantic_declaration(self) -> dict[str, Any]:
        return BodyUniverseDto(
            name=self.euf_key,
            out_binding="out",
            inv=_formula_to_rpc(self.denotation()),
        ).to_rpc()

    @classmethod
    def verdict_witnesses(cls) -> VerdictWitnessPair:
        call = ctor("call:A", [])
        key = canonical_euf_callsite_name(call)
        stated_truth = cls(
            euf_key=key,
            call_term=call,
            rhs_term=num(0),
            provenance=_witness_provenance(cls.node_class, warrants=("Stated",)),
        )
        derived_truth = cls(
            euf_key=key,
            call_term=call,
            rhs_term=num(0),
            provenance=_witness_provenance(cls.node_class, warrants=("Derived",)),
        )
        truthful = merge_equality_facts(stated_truth, derived_truth)
        stated_lie = cls(
            euf_key=key,
            call_term=call,
            rhs_term=num(1),
            provenance=_witness_provenance(cls.node_class, warrants=("Stated",)),
        )
        derived = cls(
            euf_key=key,
            call_term=call,
            rhs_term=num(0),
            provenance=_witness_provenance(cls.node_class, warrants=("Derived",)),
        )
        return VerdictWitnessPair(
            truthful=VerdictWitnessCase(
                name="equality-truthful-collapse",
                expected="sat",
                formulas=(truthful.denotation(),),
                declarations={"call:A": _INT_SORT},
            ),
            lying=VerdictWitnessCase(
                name="equality-stated-derived-disagreement",
                expected="unsat",
                formulas=(stated_lie.denotation(), derived.denotation()),
                declarations={"call:A": _INT_SORT},
            ),
        )


_INT_SORT = num(0).sort


@dataclass(frozen=True)
class Formal:
    name: str
    sort: Sort


@dataclass(frozen=True)
class FunctionContract(ProofIRNode):
    node_class: ClassVar[str] = "FunctionContract"

    symbol: str
    formals: tuple[Formal, ...]
    post: Formula
    warrants: tuple[Provenance, ...]
    out_binding: str = "out"
    out_sort: Sort = _INT_SORT
    pre: Formula | None = None

    def __post_init__(self) -> None:
        if not self.symbol:
            _proofir_gap(
                owner=self.node_class,
                observed="empty symbol",
                requested="callable symbol",
                fix="construct FunctionContract with the callable symbol",
            )
        if self.out_binding != "out":
            _proofir_gap(
                owner=self.node_class,
                observed=f"out binding {self.out_binding!r}",
                requested="out binding named 'out'",
                fix="use the verifier-visible output binding `out`",
            )
        if not self.warrants:
            _proofir_gap(
                owner=self.node_class,
                observed="no warrants",
                requested="at least one construction provenance",
                fix="add a provenance warrant before build()",
            )
        for warrant in self.warrants:
            _require_provenance(warrant, owner=self.node_class)
        if not _is_formula(self.post):
            _proofir_gap(
                owner=self.node_class,
                observed=type(self.post).__name__,
                requested="typed Formula post",
                fix="hand FunctionContract a typed ir.Formula, never a dict",
            )
        if self.pre is not None and not _is_formula(self.pre):
            _proofir_gap(
                owner=self.node_class,
                observed=type(self.pre).__name__,
                requested="typed Formula pre",
                fix="hand FunctionContract a typed ir.Formula, never a dict",
            )
        if not _formula_mentions_var(self.post, self.out_binding):
            _proofir_gap(
                owner=self.node_class,
                observed="post without out binding",
                requested=f"post mentioning {self.out_binding!r}",
                fix="construct the post over the verifier-visible out binding",
            )
        seen: set[str] = set()
        for formal in self.formals:
            if not formal.name:
                _proofir_gap(
                    owner=self.node_class,
                    observed="empty formal name",
                    requested="named formal with declared sort",
                    fix="declare every formal before build()",
                )
            if formal.name in seen:
                _proofir_gap(
                    owner=self.node_class,
                    observed=f"duplicate formal {formal.name!r}",
                    requested="unique formal names",
                    fix="deduplicate formals before build()",
                )
            seen.add(formal.name)

    @classmethod
    def builder(
        cls,
        *,
        symbol: str,
        out_binding: str,
        out_sort: Sort,
        provenance: Provenance,
    ) -> "FunctionContractBuilder":
        return FunctionContractBuilder(
            symbol=symbol,
            out_binding=out_binding,
            out_sort=out_sort,
            provenance=provenance,
        )

    def denotation(self) -> Formula:
        body = self.post if self.pre is None else implies(self.pre, self.post)
        for formal in reversed(self.formals):
            body = forall(formal.name, formal.sort, body)
        return body

    def provenance(self) -> Provenance:
        return self.warrants[0]

    def to_declaration(self) -> dict[str, Any]:
        return BodyUniverseDto(
            name=self.symbol,
            out_binding=self.out_binding,
            pre=_formula_to_rpc(self.pre) if self.pre is not None else None,
            post=_formula_to_rpc(self.post),
            source_warrants=[warrant.warrant_memento() for warrant in self.warrants],
            formals=[formal.name for formal in self.formals],
            kind="function-contract",
        ).to_rpc()

    @classmethod
    def verdict_witnesses(cls) -> VerdictWitnessPair:
        truthful_contract = (
            cls.builder(
                symbol="module::truthful::callable",
                out_binding="out",
                out_sort=_INT_SORT,
                provenance=_witness_provenance(cls.node_class, warrants=("Derived",)),
            )
            .post(eq(make_var("out"), num(0)))
            .build()
        )
        lying_contract = (
            cls.builder(
                symbol="module::lying::callable",
                out_binding="out",
                out_sort=_INT_SORT,
                provenance=_witness_provenance(cls.node_class, warrants=("Derived",)),
            )
            .post(eq(make_var("out"), num(1)))
            .build()
        )
        floor = eq(make_var("out"), num(0))
        return VerdictWitnessPair(
            truthful=VerdictWitnessCase(
                name="function-contract-floor-models-post",
                expected="sat",
                formulas=(truthful_contract.denotation(), floor),
                declarations={"out": _INT_SORT},
            ),
            lying=VerdictWitnessCase(
                name="function-contract-floor-contradicts-post",
                expected="unsat",
                formulas=(lying_contract.denotation(), floor),
                declarations={"out": _INT_SORT},
            ),
        )


@dataclass(frozen=True)
class FunctionContractBuilder:
    symbol: str
    out_binding: str
    out_sort: Sort
    provenance: Provenance
    _formals: tuple[Formal, ...] = ()
    _pre: Formula | None = None
    _post: object | None = None

    def formal(self, name: str, sort: Sort) -> "FunctionContractBuilder":
        return FunctionContractBuilder(
            symbol=self.symbol,
            out_binding=self.out_binding,
            out_sort=self.out_sort,
            provenance=self.provenance,
            _formals=(*self._formals, Formal(name=name, sort=sort)),
            _pre=self._pre,
            _post=self._post,
        )

    def pre(self, formula: Formula) -> "FunctionContractBuilder":
        return FunctionContractBuilder(
            symbol=self.symbol,
            out_binding=self.out_binding,
            out_sort=self.out_sort,
            provenance=self.provenance,
            _formals=self._formals,
            _pre=formula,
            _post=self._post,
        )

    def post(self, formula: object) -> "FunctionContractBuilder":
        return FunctionContractBuilder(
            symbol=self.symbol,
            out_binding=self.out_binding,
            out_sort=self.out_sort,
            provenance=self.provenance,
            _formals=self._formals,
            _pre=self._pre,
            _post=formula,
        )

    def build(self) -> FunctionContract:
        if self._post is None:
            _proofir_gap(
                owner="FunctionContract",
                observed="builder without post",
                requested="post formula",
                fix="call .post(typed_formula) before build()",
            )
        return FunctionContract(
            symbol=self.symbol,
            formals=self._formals,
            pre=self._pre,
            post=self._post,
            warrants=(self.provenance,),
            out_binding=self.out_binding,
            out_sort=self.out_sort,
        )


@dataclass(frozen=True)
class RefusalRecord(ProofIRNode):
    node_class: ClassVar[str] = "RefusalRecord"

    effect_kind: str
    reason: str
    provenance: InitVar[Provenance]
    _provenance: Provenance = field(init=False, repr=False)

    def __post_init__(self, provenance: Provenance) -> None:
        _require_provenance(provenance, owner=self.node_class)
        if not self.effect_kind:
            _proofir_gap(
                owner=self.node_class,
                observed="empty effect kind",
                requested="typed effect kind",
                fix="construct RefusalRecord from Incomplete or a typed gap",
            )
        if not self.reason:
            _proofir_gap(
                owner=self.node_class,
                observed="empty reason",
                requested="effect reason",
                fix="preserve the refusal reason when constructing RefusalRecord",
            )
        object.__setattr__(self, "_provenance", provenance)

    @classmethod
    def from_incomplete(
        cls,
        incomplete: Incomplete,
        *,
        provenance: Provenance,
        formula: Formula | None = None,
    ) -> "RefusalRecord":
        if formula is not None:
            _proofir_gap(
                owner=cls.node_class,
                observed="Outcome carried both formula and refusal",
                requested="exactly one vocabulary expression for Outcome::Incomplete",
                fix="emit either EqualityFact/FunctionContract or RefusalRecord, never both",
            )
        effect = incomplete.effect
        return cls(
            effect_kind=type(effect).__name__,
            reason=incomplete.reason,
            provenance=provenance,
        )

    @classmethod
    def from_gap(
        cls,
        gap: FactoryGap | DigRefusal,
        *,
        provenance: Provenance,
        formula: Formula | None = None,
    ) -> "RefusalRecord":
        if formula is not None:
            _proofir_gap(
                owner=cls.node_class,
                observed="gap carried both formula and refusal",
                requested="exactly one vocabulary expression for a refused gap",
                fix="emit either a fact or a refusal record, never both",
            )
        if isinstance(gap, FactoryGap):
            return cls(
                effect_kind=str(gap.info.get("gap_kind", "FactoryGap")),
                reason=str(gap),
                provenance=provenance,
            )
        return cls(effect_kind=gap.caught, reason=gap.reason, provenance=provenance)

    def denotation(self) -> None:
        return None

    def provenance(self) -> Provenance:
        return self._provenance

    def to_declaration(self) -> dict[str, Any]:
        return {
            "kind": "refusal-record",
            "effectKind": self.effect_kind,
            "reason": self.reason,
            "provenance": self.provenance().to_rpc(),
        }

    @classmethod
    def verdict_witnesses(cls) -> VerdictWitnessPair:
        return VerdictWitnessPair(
            truthful=VerdictWitnessCase(
                name="refusal-record-bridge-only",
                expected="sat",
                formulas=(),
                declarations={},
                construct=lambda: cls.from_incomplete(
                    _runtime_effect_incomplete("opaque runtime effect"),
                    provenance=_witness_provenance(cls.node_class, warrants=("Derived",)),
                ),
            ),
            lying=VerdictWitnessCase(
                name="refusal-record-fact-and-refusal-refuses",
                expected="construction-refusal",
                formulas=(),
                declarations={},
                construct=lambda: cls.from_incomplete(
                    _runtime_effect_incomplete("opaque runtime effect"),
                    provenance=_witness_provenance(cls.node_class, warrants=("Derived",)),
                    formula=eq(make_var("call"), num(0)),
                ),
            ),
        )


REGISTERED_PROOFIR_NODE_CLASSES: tuple[type[ProofIRNode], ...] = (
    EqualityFact,
    FunctionContract,
    RefusalRecord,
)


def registered_verdict_witnesses() -> tuple[tuple[str, bool, bool], ...]:
    registrations: list[tuple[str, bool, bool]] = []
    for node_class in REGISTERED_PROOFIR_NODE_CLASSES:
        pair = node_class.verdict_witnesses()
        registrations.append(
            (
                node_class.node_class,
                pair.truthful.expected == "sat",
                pair.lying.expected in {"unsat", "construction-refusal"},
            )
        )
    return tuple(registrations)


def merge_equality_facts(left: EqualityFact, right: EqualityFact) -> EqualityFact:
    if left.semantic_cid() != right.semantic_cid():
        _proofir_gap(
            owner="EqualityFact.merge",
            observed=(
                f"left semantic_cid={left.semantic_cid()} "
                f"right semantic_cid={right.semantic_cid()}"
            ),
            requested="equal semantic_cid for EqualityFact merge",
            fix="keep disagreeing stated/derived facts as separate formulas",
        )
    if left.provenance() == right.provenance():
        return left
    merged_provenance = _merge_provenance(left.provenance(), right.provenance())
    return EqualityFact(
        euf_key=left.euf_key,
        call_term=left.call_term,
        rhs_term=left.rhs_term,
        provenance=merged_provenance,
    )


def canonical_euf_callsite_name(call_term: Term, *, suffix: str = "::assertion") -> str:
    if not isinstance(call_term, _Ctor) or not call_term.name.startswith("call:"):
        _proofir_gap(
            owner="EqualityFact",
            observed=repr(call_term),
            requested="call:<callee> ctor term",
            fix="derive #euf# keys only from euf_call_term outputs",
        )
    callee = call_term.name.removeprefix("call:")
    return f"{callee}#euf#{_canonical_term_sig(call_term)}{suffix}"


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


def _is_formula(formula: object) -> bool:
    return isinstance(formula, (_Atomic, _Connective, _Quantifier))


def _formula_mentions_var(formula: Formula, name: str) -> bool:
    if isinstance(formula, _Atomic):
        return any(_term_mentions_var(term, name) for term in formula.args)
    if isinstance(formula, _Connective):
        return any(_formula_mentions_var(operand, name) for operand in formula.operands)
    if isinstance(formula, _Quantifier):
        if formula.name == name:
            return False
        return _formula_mentions_var(formula.body, name)
    return False


def _term_mentions_var(term: Term, name: str) -> bool:
    if isinstance(term, _Var):
        return term.name == name
    if isinstance(term, _Ctor):
        return any(_term_mentions_var(arg, name) for arg in term.args)
    return False


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


def _runtime_effect_incomplete(reason: str) -> Incomplete:
    from sugar_lift_py_tests.effect import RuntimeEffect

    return Incomplete(RuntimeEffect(reason))


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
) -> None:
    info = FactoryGapInfo(
        owner=owner,
        blame="proofir-vocabulary",
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind="ProofIR",
        gap_locus="Vocabulary",
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
