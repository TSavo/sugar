from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Iterable, Mapping

from sugar_lift_py_tests.ir import (
    Formula as IrFormula,
    Sort as IrSort,
    Term as IrTerm,
    _Atomic,
    _Connective,
    _ConstBool,
    _ConstInt,
    _ConstReal,
    _ConstStr,
    _Ctor,
    eq,
    bool_const,
    forall,
    implies,
    make_var,
    num,
)
from sugar_lift_py_tests.kit_rpc import BodyUniverseDto, SourceMementoDto
from sugar_lift_py_tests.proofir.formulas import formula_from_ir
from sugar_lift_py_tests.proofir.scope import (
    PostCondition,
    PreCondition,
    claim_formula_from_ir,
)
from sugar_lift_py_tests.proofir.sorts import IntSort, Sort, sort_from_ir

from . import (
    Provenance,
    ProofIRNode,
    VerdictWitnessCase,
    VerdictWitnessPair,
    _INT_SORT,
    _formula_to_rpc,
    _lying_source,
    _proofir_gap,
    _require_provenance,
    _truthful_source,
    _witness_provenance,
)

SourceWarrant = SourceMementoDto | dict[str, Any]


@dataclass(frozen=True)
class Formal:
    name: str
    sort: Sort


@dataclass(frozen=True, init=False)
class FunctionContract(ProofIRNode):
    node_class: ClassVar[str] = "FunctionContract"

    symbol: str = field(init=False)
    formals: tuple[Formal, ...] = field(init=False)
    post: PostCondition = field(init=False)
    warrants: tuple[Provenance, ...] = field(init=False)
    out_binding: str = field(init=False, default="out")
    out_sort: Sort = field(init=False)
    pre: PreCondition | None = field(init=False, default=None)
    bridge_source_symbol: str | None = field(init=False, default=None)
    source_warrants: tuple[SourceWarrant, ...] = field(init=False, default=())

    def __init__(
        self,
        *,
        symbol: str,
        formals: Iterable[Formal],
        post: PostCondition,
        warrants: Iterable[Provenance],
        out_binding: str = "out",
        out_sort: Sort | IrSort | None = None,
        pre: PreCondition | None = None,
        bridge_source_symbol: str | None = None,
        source_warrants: Iterable[SourceWarrant] = (),
    ) -> None:
        if not isinstance(post, PostCondition):
            raise TypeError("FunctionContract post must be PostCondition")
        if pre is not None and not isinstance(pre, PreCondition):
            raise TypeError("FunctionContract pre must be PreCondition")
        normalized_formals = tuple(formals)
        normalized_warrants = tuple(warrants)
        normalized_out_sort = (
            _normalize_sort(out_sort) if out_sort is not None else post.out_sort
        )
        _validate_contract(
            symbol=symbol,
            formals=normalized_formals,
            warrants=normalized_warrants,
            out_binding=out_binding,
            post=post,
            pre=pre,
            out_sort=normalized_out_sort,
        )
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "formals", normalized_formals)
        object.__setattr__(self, "post", post)
        object.__setattr__(self, "warrants", normalized_warrants)
        object.__setattr__(self, "out_binding", out_binding)
        object.__setattr__(self, "out_sort", normalized_out_sort)
        object.__setattr__(self, "pre", pre)
        object.__setattr__(self, "bridge_source_symbol", bridge_source_symbol)
        object.__setattr__(self, "source_warrants", tuple(source_warrants))

    @staticmethod
    def formal(name: str, sort: Sort | IrSort) -> Formal:
        return Formal(name=name, sort=_normalize_sort(sort))

    @classmethod
    def builder(
        cls,
        *,
        symbol: str,
        out_binding: str,
        out_sort: Sort | IrSort,
        provenance: Provenance,
        bridge_source_symbol: str | None = None,
        source_warrants: Iterable[SourceWarrant] = (),
    ) -> FunctionContractBuilder:
        return FunctionContractBuilder(
            symbol=symbol,
            out_binding=out_binding,
            out_sort=_normalize_sort(out_sort),
            provenance=provenance,
            bridge_source_symbol=bridge_source_symbol,
            source_warrants=tuple(source_warrants),
        )

    def denotation(self) -> IrFormula:
        body = (
            self.post.ir_formula
            if self.pre is None
            else implies(self.pre.ir_formula, self.post.ir_formula)
        )
        for formal in reversed(self.formals):
            body = forall(formal.name, formal.sort.ir_sort, body)
        return body

    def provenance(self) -> Provenance:
        return self.warrants[0]

    def to_declaration(self) -> dict[str, Any]:
        return self.to_body_universe().to_rpc()

    def to_body_universe(self) -> BodyUniverseDto:
        source_warrants = list(self.source_warrants) or [
            warrant.warrant_memento() for warrant in self.warrants
        ]
        return BodyUniverseDto(
            name=self.symbol,
            out_binding=self.out_binding,
            pre=(
                _claim_formula_for_pre(self.pre, provenance=self.provenance())
                if self.pre is not None
                else None
            ),
            post=_claim_formula_for_post(self.post, provenance=self.provenance()),
            source_warrants=source_warrants,
            formals=[formal.name for formal in self.formals],
            kind="function-contract",
            bridge_source_symbol=self.bridge_source_symbol,
        )

    def floor_models_post(
        self,
        *,
        arg_terms: list[IrTerm],
        floor_term: IrTerm,
    ) -> bool | None:
        env = {formal.name: term for formal, term in zip(self.formals, arg_terms)}
        env[self.out_binding] = floor_term
        return _formula_models_post(self.post.ir_formula, env)

    @classmethod
    def verdict_witnesses(cls) -> VerdictWitnessPair:
        truthful_contract = (
            cls.builder(
                symbol="module::truthful::callable",
                out_binding="out",
                out_sort=IntSort(),
                provenance=_witness_provenance(cls.node_class, warrants=("Derived",)),
            )
            .post(_post_from_ir(eq(make_var("out"), num(0)), {}, out_sort=IntSort()))
            .build()
        )
        lying_contract = (
            cls.builder(
                symbol="module::lying::callable",
                out_binding="out",
                out_sort=IntSort(),
                provenance=_witness_provenance(cls.node_class, warrants=("Derived",)),
            )
            .post(_post_from_ir(eq(make_var("out"), num(1)), {}, out_sort=IntSort()))
            .build()
        )
        floor = eq(make_var("out"), num(0))
        return VerdictWitnessPair(
            truthful=VerdictWitnessCase(
                name="function-contract-floor-models-post",
                expected="sat",
                formulas=(truthful_contract.denotation(), floor),
                declarations={"out": _INT_SORT},
                source=_truthful_source(),
                node_class=cls.node_class,
                expected_sugar="python.literal-call-sugar",
            ),
            lying=VerdictWitnessCase(
                name="function-contract-floor-contradicts-post",
                expected="unsat",
                formulas=(lying_contract.denotation(), floor),
                declarations={"out": _INT_SORT},
                source=_lying_source(),
                node_class=cls.node_class,
                expected_sugar="python.literal-call-sugar",
            ),
        )


@dataclass(frozen=True)
class FunctionContractBuilder:
    symbol: str
    out_binding: str
    out_sort: Sort
    provenance: Provenance
    bridge_source_symbol: str | None = None
    source_warrants: tuple[SourceWarrant, ...] = ()
    _formals: tuple[Formal, ...] = ()
    _pre: PreCondition | None = None
    _post: object | None = None

    def formal(self, name: str, sort: Sort | IrSort) -> FunctionContractBuilder:
        return FunctionContractBuilder(
            symbol=self.symbol,
            out_binding=self.out_binding,
            out_sort=self.out_sort,
            provenance=self.provenance,
            bridge_source_symbol=self.bridge_source_symbol,
            source_warrants=self.source_warrants,
            _formals=(*self._formals, Formal(name=name, sort=_normalize_sort(sort))),
            _pre=self._pre,
            _post=self._post,
        )

    def pre(self, condition: PreCondition) -> FunctionContractBuilder:
        if not isinstance(condition, PreCondition):
            raise TypeError("FunctionContract pre must be PreCondition")
        return FunctionContractBuilder(
            symbol=self.symbol,
            out_binding=self.out_binding,
            out_sort=self.out_sort,
            provenance=self.provenance,
            bridge_source_symbol=self.bridge_source_symbol,
            source_warrants=self.source_warrants,
            _formals=self._formals,
            _pre=condition,
            _post=self._post,
        )

    def post(self, condition: PostCondition) -> FunctionContractBuilder:
        if not isinstance(condition, PostCondition):
            raise TypeError("FunctionContract post must be PostCondition")
        return FunctionContractBuilder(
            symbol=self.symbol,
            out_binding=self.out_binding,
            out_sort=self.out_sort,
            provenance=self.provenance,
            bridge_source_symbol=self.bridge_source_symbol,
            source_warrants=self.source_warrants,
            _formals=self._formals,
            _pre=self._pre,
            _post=condition,
        )

    def build(self) -> FunctionContract:
        if self._post is None:
            _proofir_gap(
                owner="FunctionContract",
                observed="builder without post",
                requested="PostCondition",
                fix="call .post(PostCondition(...)) before build()",
            )
        return FunctionContract(
            symbol=self.symbol,
            formals=self._formals,
            pre=self._pre,
            post=self._post,
            warrants=(self.provenance,),
            out_binding=self.out_binding,
            out_sort=self.out_sort,
            bridge_source_symbol=self.bridge_source_symbol,
            source_warrants=self.source_warrants,
        )


def _post_from_ir(
    ir_formula: IrFormula,
    formals: Mapping[str, Sort],
    *,
    out_sort: Sort,
    out_binding: str = "out",
) -> PostCondition:
    var_sorts = {**formals, out_binding: out_sort}
    return PostCondition(
        formula_from_ir(ir_formula, var_sorts=var_sorts),
        formals=formals,
        out_binding=out_binding,
        out_sort=out_sort,
    )


def _claim_formula_for_post(
    condition: PostCondition,
    *,
    provenance: Provenance,
) -> object:
    var_sorts = {**condition.formals, condition.out_binding: condition.out_sort}
    return claim_formula_from_ir(
        condition.ir_formula,
        var_sorts=var_sorts,
        allowed_vars=var_sorts.keys(),
        provenance=provenance,
        role="FunctionContract.post",
    )


def _claim_formula_for_pre(
    condition: PreCondition,
    *,
    provenance: Provenance,
) -> object:
    return claim_formula_from_ir(
        condition.ir_formula,
        var_sorts=condition.formals,
        allowed_vars=condition.formals.keys(),
        provenance=provenance,
        role="FunctionContract.pre",
    )


def _validate_contract(
    *,
    symbol: str,
    formals: tuple[Formal, ...],
    warrants: tuple[Provenance, ...],
    out_binding: str,
    post: PostCondition,
    pre: PreCondition | None,
    out_sort: Sort,
) -> None:
    if not symbol:
        _proofir_gap(
            owner=FunctionContract.node_class,
            observed="empty symbol",
            requested="callable symbol",
            fix="construct FunctionContract with the callable symbol",
        )
    if out_binding != post.out_binding:
        _proofir_gap(
            owner=FunctionContract.node_class,
            observed=f"out binding {out_binding!r}",
            requested=f"post out binding {post.out_binding!r}",
            fix="use one verifier-visible output binding for the contract",
        )
    if out_sort != post.out_sort:
        _proofir_gap(
            owner=FunctionContract.node_class,
            observed=f"out sort {out_sort.name} vs post {post.out_sort.name}",
            requested="contract out sort matches PostCondition",
            fix="construct the PostCondition from the contract's return sort",
        )
    if not warrants:
        _proofir_gap(
            owner=FunctionContract.node_class,
            observed="no warrants",
            requested="at least one construction provenance",
            fix="add a provenance warrant before build()",
        )
    for warrant in warrants:
        _require_provenance(warrant, owner=FunctionContract.node_class)
    seen: set[str] = set()
    for formal in formals:
        if not formal.name:
            _proofir_gap(
                owner=FunctionContract.node_class,
                observed="empty formal name",
                requested="named formal with declared sort",
                fix="declare every formal before build()",
            )
        if formal.name in seen:
            _proofir_gap(
                owner=FunctionContract.node_class,
                observed=f"duplicate formal {formal.name!r}",
                requested="unique formal names",
                fix="deduplicate formals before build()",
            )
        seen.add(formal.name)
    expected_formals = {formal.name: formal.sort for formal in formals}
    if dict(post.formals) != expected_formals:
        _proofir_gap(
            owner=FunctionContract.node_class,
            observed="PostCondition scope differs from FunctionContract formals",
            requested="matching contract and postcondition scopes",
            fix="build the PostCondition with the same formal sort map as the contract",
        )
    if pre is not None and dict(pre.formals) != expected_formals:
        _proofir_gap(
            owner=FunctionContract.node_class,
            observed="PreCondition scope differs from FunctionContract formals",
            requested="matching contract and precondition scopes",
            fix="build the PreCondition with the same formal sort map as the contract",
        )


def _normalize_sort(sort: Sort | IrSort) -> Sort:
    if isinstance(sort, Sort):
        return sort
    return sort_from_ir(sort)


def _formula_models_post(formula: IrFormula, env: dict[str, IrTerm]) -> bool | None:
    if isinstance(formula, _Atomic) and formula.name == "=":
        if len(formula.args) != 2:
            return None
        left = _normalize_ir_term(formula.args[0], env)
        right = _normalize_ir_term(formula.args[1], env)
        return left == right if left is not None and right is not None else None
    if isinstance(formula, _Connective) and formula.kind == "and":
        verdicts = [_formula_models_post(operand, env) for operand in formula.operands]
        if any(verdict is False for verdict in verdicts):
            return False
        if all(verdict is True for verdict in verdicts):
            return True
        return None
    return None


def _normalize_ir_term(term: IrTerm, env: dict[str, IrTerm]) -> IrTerm | None:
    if isinstance(term, (_ConstInt, _ConstStr, _ConstBool, _ConstReal)):
        return term
    if isinstance(term, _Ctor):
        normalized_args = [_normalize_ir_term(arg, env) for arg in term.args]
        if any(arg is None for arg in normalized_args):
            return None
        return _fold_numeric_ctor(term.name, normalized_args) or _Ctor(
            term.name,
            tuple(arg for arg in normalized_args if arg is not None),
        )
    if hasattr(term, "name"):
        name = getattr(term, "name")
        return env.get(name) if isinstance(name, str) else None
    return None


def _fold_numeric_ctor(name: str, args: list[IrTerm | None]) -> IrTerm | None:
    if (
        name == "py.subscript"
        and len(args) == 2
        and isinstance(args[0], _Ctor)
        and args[0].name in {"array", "tuple"}
        and isinstance(args[1], _ConstInt)
    ):
        index = args[1].value
        if 0 <= index < len(args[0].args):
            return args[0].args[index]
        return None
    if (
        name == "divmod"
        and len(args) == 2
        and all(isinstance(arg, _ConstInt) for arg in args)
    ):
        left, right = (arg.value for arg in args if isinstance(arg, _ConstInt))
        if right == 0:
            return None
        quotient, remainder = divmod(left, right)
        return _Ctor("tuple", (num(quotient), num(remainder)))
    if (
        name.startswith("py.compare:")
        and len(args) == 2
        and all(isinstance(arg, _ConstInt) for arg in args)
    ):
        left, right = (arg.value for arg in args if isinstance(arg, _ConstInt))
        operator = name.removeprefix("py.compare:")
        if operator == "Lt":
            return bool_const(left < right)
        if operator == "LtE":
            return bool_const(left <= right)
        if operator == "Gt":
            return bool_const(left > right)
        if operator == "GtE":
            return bool_const(left >= right)
        if operator == "NotEq":
            return bool_const(left != right)
        if operator == "Eq":
            return bool_const(left == right)
    if name in {"==", "!="} and len(args) == 2:
        left, right = args
        if type(left) is type(right) and isinstance(
            left, (_ConstBool, _ConstInt, _ConstReal, _ConstStr)
        ):
            equal = left == right
            return bool_const(equal if name == "==" else not equal)
    if name not in {"+", "-", "*"}:
        return None
    if not all(isinstance(arg, _ConstInt) for arg in args):
        return None
    values = [arg.value for arg in args if isinstance(arg, _ConstInt)]
    if name == "+":
        return num(sum(values))
    if name == "*":
        value = 1
        for item in values:
            value *= item
        return num(value)
    if name == "-" and len(values) == 1:
        return num(-values[0])
    if name == "-" and len(values) == 2:
        return num(values[0] - values[1])
    return None


__all__ = ["Formal", "FunctionContract", "FunctionContractBuilder"]
