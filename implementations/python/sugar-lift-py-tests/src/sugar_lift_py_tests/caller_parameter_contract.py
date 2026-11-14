from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace
import json
from typing import Any

from sugar_lift_py_tests.canonicalizer import blake3_512_of, encode_jcs
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.context_manager_contract import _json_value
from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus
from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.ir import (
    Formula,
    Term,
    atomic,
    ctor,
    formula_to_value,
    str_const,
    term_to_value,
)


class NativeOperationResolutionV1:
    """The closed caller-discharge result for one native operation.

    The exceptional arm is authenticated only when both the exception type
    coordinate and operation occurrence coordinate are present.  A halt without
    those coordinates is not a fourth exit kind: it remains ``undischarged``.
    """

    __slots__ = (
        "_kind",
        "value",
        "exception_type_coordinate",
        "raise_occurrence_coordinate",
        "effect",
        "pre_effect_state",
        "reason",
    )

    def __init__(
        self,
        *,
        kind,
        value=None,
        exception_type_coordinate=None,
        raise_occurrence_coordinate=None,
        effect=None,
        pre_effect_state=None,
        reason=None,
    ):
        if kind not in {"completed", "exceptional", "undischarged"}:
            raise ValueError(f"unknown native operation resolution: {kind}")
        if kind == "completed" and value is None:
            raise ValueError("completed native operation requires a value")
        if kind == "exceptional" and (
            exception_type_coordinate is None or raise_occurrence_coordinate is None
        ):
            raise ValueError(
                "exceptional native operation requires authenticated type and occurrence"
            )
        if kind == "undischarged" and not reason:
            raise ValueError("undischarged native operation requires a reason")
        if kind != "exceptional" and (
            exception_type_coordinate is not None
            or raise_occurrence_coordinate is not None
        ):
            raise ValueError(
                "non-exceptional resolution cannot carry exception testimony"
            )
        self._kind = kind
        self.value = value
        self.exception_type_coordinate = exception_type_coordinate
        self.raise_occurrence_coordinate = raise_occurrence_coordinate
        self.effect = effect
        self.pre_effect_state = pre_effect_state
        self.reason = reason

    @classmethod
    def completed(cls, value):
        return cls(kind="completed", value=value)

    @classmethod
    def exceptional(
        cls,
        *,
        exception_type_coordinate,
        operation_occurrence,
        effect=None,
        pre_effect_state=None,
    ):
        if pre_effect_state is not None and not isinstance(
            pre_effect_state, ReducerPreEffectStateV1
        ):
            raise TypeError(
                "exceptional native operation requires reducer-issued "
                "pre-effect-state testimony"
            )
        return cls(
            kind="exceptional",
            exception_type_coordinate=exception_type_coordinate,
            raise_occurrence_coordinate=operation_occurrence,
            effect=effect,
            pre_effect_state=pre_effect_state,
        )

    @classmethod
    def undischarged(cls, reason: str):
        return cls(kind="undischarged", reason=reason)

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def is_completed(self) -> bool:
        return self._kind == "completed"

    @property
    def has_authenticated_exception_type(self) -> bool:
        return (
            self._kind == "exceptional"
            and self.exception_type_coordinate is not None
            and self.raise_occurrence_coordinate is not None
        )

    @property
    def is_undischarged(self) -> bool:
        return self._kind == "undischarged"

    @property
    def is_exceptional(self) -> bool:
        return self._kind == "exceptional"

    @property
    def is_authenticated_exceptional_exit(self) -> bool:
        """The only resolution arm admitted to an authenticated-exit tally."""
        return self.has_authenticated_exception_type

    def project(self, *, source_node):
        """Project the closed resolution into an ExitSet or a typed refusal."""
        from sugar_lift_py_tests.effect import RaiseEffect
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_source_tree.panic import SugarNotWritten

        if self.is_completed:
            return ExitSet.completed(self.value)
        if self.has_authenticated_exception_type:
            occurrence = self.raise_occurrence_coordinate
            assert occurrence is not None
            testimony = self.pre_effect_state
            effect = self.effect
            if testimony is None:
                effect = RaiseEffect(
                    exception_type_coordinate=self.exception_type_coordinate,
                    occurrence=AuthenticatedRaiseLocus.of(str(occurrence.wire())),
                    blame=str(occurrence.wire()),
                )
            if not isinstance(effect, RaiseEffect):
                raise TypeError(
                    "exceptional native operation effect must be RaiseEffect"
                )
            return ExitSet.halted(
                effect,
                state=(None if testimony is None else testimony.state),
            )
        raise SugarNotWritten(
            blame=str(source_node),
            owner="NativeOperationResolutionV1.project",
            observed=self.reason or "native operation exception identity unproven",
            requested="authenticated exception type and operation occurrence coordinates",
            fix="retain the operation as undischarged until both coordinates are proven",
        )


_REDUCER_PRE_EFFECT_STATE_SEAL = object()


@dataclass(frozen=True)
class ReducerPreEffectStateV1:
    """Reducer-issued testimony for the exact state preceding one operation.

    The constructor is sealed: callers cannot pass a raw empty block, receiver,
    or post-store value and have it mistaken for temporal testimony.  The sole
    mint is called by ``reduce_block_to_exitset`` at carrier enrollment.
    """

    state: object
    _seal: object = dataclass_field(repr=False, compare=False)

    def __post_init__(self):
        if self._seal is not _REDUCER_PRE_EFFECT_STATE_SEAL:
            raise TypeError(
                "pre-effect state must be issued by reduce_block_to_exitset"
            )

    @classmethod
    def _from_reducer(cls, state):
        if state is None:
            raise TypeError("reducer pre-effect state cannot be absent")
        if (
            type(state).__name__ != "_ReducedBlock"
            or type(state).__module__
            != "sugar_lift_py_tests.sugar.function_universe_sugar"
        ):
            raise TypeError(
                "reducer pre-effect state must be the live _ReducedBlock, not "
                f"{type(state).__name__}"
            )
        return cls(state=state, _seal=_REDUCER_PRE_EFFECT_STATE_SEAL)


def authenticated_exceptional_resolution_count(resolutions) -> int:
    """Count named exceptional resolutions by coordinates, never by arm kind."""
    return sum(
        resolution.is_authenticated_exceptional_exit for resolution in resolutions
    )


def _json(value) -> Any:
    return json.loads(encode_jcs(value))


def _cid(value: Any) -> str:
    return blake3_512_of(encode_jcs(_json_value(value)).encode("utf-8"))


def source_coordinate(site) -> SourceFragmentCoordinateV1:
    span = site.line_col_span
    return SourceFragmentCoordinateV1(
        site.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def native_operator_demand(operator: str, operands: tuple[Term, ...]) -> Formula:
    """The unresolved caller obligation for one ordered native operation.

    This formula records a question.  It does not choose a result, an exception
    type, or a runtime coordinate; caller discharge supplies authenticated
    actual operands and the ordinary Floor answers the question later.
    """
    return atomic(
        "python:native_operator_demand",
        [str_const(operator), *operands],
    )


@dataclass(frozen=True)
class NativeOperationDemandV1:
    """Content identity for an ordered native-operation occurrence."""

    source_node: SourceFragmentCoordinateV1
    operator: str
    operand_terms: tuple[Term, ...]
    operand_coordinate_cids: tuple[str | None, ...]
    candidate: Term
    candidate_cid: str
    demanded_formula: Formula
    demand_cid: str

    @classmethod
    def mint(cls, *, site, operator, operands, coordinates):
        if not isinstance(operator, str) or not operator:
            raise ValueError("native operation requires a nonempty operator")
        operands = tuple(operands)
        coordinates = tuple(coordinates)
        if not operands or len(coordinates) != len(operands):
            raise ValueError(
                "native operation requires ordered operands and aligned coordinates"
            )

        source_node = source_coordinate(site)
        operand_terms = tuple(
            operand.to_term(owner=f"native operation {operator} operand")
            for operand in operands
        )
        coordinate_cids = tuple(
            None if coordinate is None else coordinate.coordinate_cid
            for coordinate in coordinates
        )
        candidate = ctor(
            "python:native_operation",
            [str_const(operator), *operand_terms],
        )
        candidate_preimage = {
            "kind": "native-operation-candidate",
            "schemaVersion": "1",
            "sourceNode": source_node.wire(),
            "operator": operator,
            "operands": [_json(term_to_value(term)) for term in operand_terms],
            "formalCoordinates": list(coordinate_cids),
            "candidate": _json(term_to_value(candidate)),
        }
        candidate_cid = _cid(candidate_preimage)
        demanded_formula = native_operator_demand(operator, operand_terms)
        demand_preimage = {
            "kind": "native-operation-demand",
            "schemaVersion": "1",
            "sourceNode": source_node.wire(),
            "operator": operator,
            "operands": [_json(term_to_value(term)) for term in operand_terms],
            "formalCoordinates": list(coordinate_cids),
            "candidateCid": candidate_cid,
            "demandedFormula": _json(formula_to_value(demanded_formula)),
        }
        return cls(
            source_node=source_node,
            operator=operator,
            operand_terms=operand_terms,
            operand_coordinate_cids=coordinate_cids,
            candidate=candidate,
            candidate_cid=candidate_cid,
            demanded_formula=demanded_formula,
            demand_cid=_cid(demand_preimage),
        )


def _typed_minted_native_operator_constants() -> frozenset[str]:
    """String ``operator=`` kwargs that feed native-operation carrier mints.

    Discovers:

    * ``NativeOperationExitCarrierV1.mint(operator="...")`` literals
    * ``defer_formal_native_operation(..., operator="...")`` and other call
      sites that pass a floor-method name through to ``mint``

    Dynamic ``operator=owner`` / ``operator=method`` paths are not string
    constants; :func:`production_native_operation_operators` unions the tables
    those paths draw from so the coverage tooth still closes both directions.

    Single-character / non-identifier strings (e.g. ``BinaryOperatorOperation``
    term coordinates ``"+"``) are excluded — those are term spellings, not
    carrier operator names.
    """
    from pathlib import Path
    from sugar_source_tree.nodes import Call, Constant
    from sugar_source_tree.tree import SourceFile

    package_root = Path(__file__).resolve().parent
    found: set[str] = set()
    for path in package_root.rglob("*.py"):
        if path.name == "caller_parameter_contract.py":
            # This module defines projectors and mint plumbing, not producers.
            continue
        source_file = SourceFile.from_path(path)
        registered = (
            source_file.constructed_module.construction_event_receipt.registered_occurrences
        )
        for node in registered:
            if not isinstance(node, Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "operator":
                    continue
                value = keyword.value
                if not (isinstance(value, Constant) and isinstance(value.value, str)):
                    continue
                name = value.value
                # Carrier operators are Floor method names (identifiers), never
                # binary term spellings like "+" / "//".
                if name.isidentifier():
                    found.add(name)
    return frozenset(found)


def production_native_operation_operators() -> frozenset[str]:
    """Every operator production code mints onto the native-operation carrier.

    Sources (union — each is a real mint path, not a guess):

    * typed source string constants on
      ``NativeOperationExitCarrierV1.mint(operator=...)``
    * ``_BINARY_OPERATOR_COORDINATE`` keys (``operator=owner`` formal binary path)
    * ``COMPARE_METHODS`` values (``operator=method`` formal ordering path)
    * contracted store operators whose producers pin the mint shape for this
      table even when the live store path still carries dual-face Incomplete
      instrumentation (``setitem`` window 10876, ``setattr_named`` window 17534)

    The projector table's key set must equal this set exactly, both directions.
    """
    from sugar_lift_py_tests.floor.floor_value import _BINARY_OPERATOR_COORDINATE
    from sugar_lift_py_tests.sugar.comparison_op_sugar import COMPARE_METHODS

    # Store/delete producers pin these operator strings for n-ary discharge.
    # Keep them in the production set so a missing projector cannot merge green.
    # Equality tooth: this frozenset union MUST equal
    # frozenset(_NATIVE_OPERATION_PROJECTORS) both directions.
    contracted_store_operators = frozenset(
        {"setitem", "setattr_named", "delitem", "delattr_named"}
    )
    # AugAssign production mint set — from BinaryOperator class attributes,
    # NEVER from the projector table (circular equality tooth).
    from sugar_source_tree.operators import production_augassign_inplace_operators

    contracted_inplace_operators = production_augassign_inplace_operators()
    return (
        _typed_minted_native_operator_constants()
        | frozenset(_BINARY_OPERATOR_COORDINATE)
        | frozenset(COMPARE_METHODS.values())
        | contracted_store_operators
        | contracted_inplace_operators
    )


def _project_delitem(receiver, index, site):
    """Python protocol ``__delitem__(self, key)`` — discharge order (receiver, index).

    Ordered operands and formal coordinates match this signature exactly.
    Name deletion (``del name``) is out of scope for this projector.
    """
    return receiver.delitem(index, site)


def _project_delattr_named(receiver, name, site):
    """Python protocol ``__delattr__(self, name)`` — (receiver, StringValue name).

    ``name`` arrives as StringValue from the mint; unwrap with ``.value``.
    Readability never authorizes deletion: Floor ``delattr`` refuses
    getter-only properties without consulting the read path.
    """
    return receiver.delattr(name.value, site)


def project_iadd(left, right, site):
    """Discharge ``iadd`` via established ``inplace_binary_operator_with`` edge."""
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        discharge_inplace,
    )

    return discharge_inplace(left, right, site, surface="+")


def project_isub(left, right, site):
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        discharge_inplace,
    )

    return discharge_inplace(left, right, site, surface="-")


def project_imul(left, right, site):
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        discharge_inplace,
    )

    return discharge_inplace(left, right, site, surface="*")


def project_itruediv(left, right, site):
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        discharge_inplace,
    )

    return discharge_inplace(left, right, site, surface="/")


def project_ifloordiv(left, right, site):
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        discharge_inplace,
    )

    return discharge_inplace(left, right, site, surface="//")


def project_imod(left, right, site):
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        discharge_inplace,
    )

    return discharge_inplace(left, right, site, surface="%")


def project_ipow(left, right, site):
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        discharge_inplace,
    )

    return discharge_inplace(left, right, site, surface="**")


def project_iand(left, right, site):
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        discharge_inplace,
    )

    return discharge_inplace(left, right, site, surface="&")


def project_ior(left, right, site):
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        discharge_inplace,
    )

    return discharge_inplace(left, right, site, surface="|")


def project_ixor(left, right, site):
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        discharge_inplace,
    )

    return discharge_inplace(left, right, site, surface="^")


def project_ilshift(left, right, site):
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        discharge_inplace,
    )

    return discharge_inplace(left, right, site, surface="<<")


def project_irshift(left, right, site):
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        discharge_inplace,
    )

    return discharge_inplace(left, right, site, surface=">>")


def project_imatmul(left, right, site):
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        discharge_inplace,
    )

    return discharge_inplace(left, right, site, surface="@")


def project_iter(receiver, site):
    """``iter(receiver)`` — established ``iter_with`` floor edge.

    Not yet enrolled in ``_NATIVE_OPERATION_PROJECTORS``: production has no
    carrier mint for ``iter`` until loop/comprehension demand lands. Callers
    and acceptance tests use this named projector; enrollment joins the
    production set when the first sugar mints the operator.
    """
    from sugar_lift_py_tests.operations.iterator_operation import discharge_iter

    return discharge_iter(receiver, site, owner="project_iter")


def project_next(receiver, site):
    """``next(receiver)`` — established ``next_with`` floor edge.

    Same enrollment deferral as :func:`project_iter`: surface is live; the
    native-operation table stays closed until a production mint exists.
    """
    from sugar_lift_py_tests.operations.next_operation import discharge_next

    return discharge_next(receiver, site, owner="project_next")


# Enrolled i* projectors — keys must equal production_augassign_inplace_operators().
# Selection is operator-owned (BinaryOperator.project_inplace); this table is
# discharge enrollment only — not a kind ladder.
_INPLACE_NATIVE_OPERATION_PROJECTORS = {
    "iadd": project_iadd,
    "isub": project_isub,
    "imul": project_imul,
    "itruediv": project_itruediv,
    "ifloordiv": project_ifloordiv,
    "imod": project_imod,
    "ipow": project_ipow,
    "iand": project_iand,
    "ior": project_ior,
    "ixor": project_ixor,
    "ilshift": project_ilshift,
    "irshift": project_irshift,
    "imatmul": project_imatmul,
}


# Explicit projectors for authenticated native operations.
#
# Each entry names its own Floor signature.  A generic
# ``operation(*operands, site)`` splat would conceal argument-order defects
# (swapped index/value still calls cleanly and yields a plausible wrong
# answer).  The table is the contract: producers mint operands in the
# *discharge* order these parameters declare.
#
# Discharge order for stores is not source evaluation order.  Python evaluates
# ``receiver[index] = value`` as RHS, then receiver, then index — but the
# resolved operation is called as ``receiver.setitem(index, value)``.  Those
# two orders are distinct; producers (windows 10876 / 17534) own the source
# chain, and these projectors own the call signature.
#
# Delete protocol (store-family twin):
#   delitem        → ``receiver.delitem(index, site)``   (__delitem__)
#   delattr_named  → ``receiver.delattr(name.value, site)`` (__delattr__)
# Name deletion (``del name`` / DeleteNameSugar) is out of scope here.
#
# In-place protocol (AugAssign formal path):
#   explicit project_iadd / project_isub / … each call Floor methods directly.
#   Production mint names come from BinaryOperator.inplace_operator (independent
#   equality tooth).  Projector absence must never silent-fallback to minting
#   ordinary ``add``.
#
# Key set must equal :func:`production_native_operation_operators` exactly.
def _project_unary_minus(value, site):
    """Python ``-x`` — unary Floor method; discharge arity 1."""
    return value.unary_minus(site)


def _project_unary_plus(value, site):
    """Python ``+x`` — unary Floor method; discharge arity 1."""
    return value.unary_plus(site)


def _project_bitwise_invert(value, site):
    """Python ``~x`` — unary Floor method; discharge arity 1."""
    return value.bitwise_invert(site)


def _project_method_call(receiver, name, keyword_names, *operands_and_site):
    """``receiver.<name>(*args, **kwargs)`` re-dispatched on resolved actuals.

    ``name`` is a StringValue; ``keyword_names`` a TupleValue of StringValues
    naming the trailing operands that are keyword actuals.  The receiver's
    actual selects the method exactly as MethodCallSugar does (a floor's
    method body, the container law, or the #7616 two faces); an actual that
    is still a formal defers again to its own caller."""
    from sugar_lift_py_tests.sugar.method_call_sugar import dispatch_method_call

    *operands, site = operands_and_site
    names = tuple(element.value for element in keyword_names.elements)
    split = len(operands) - len(names)
    positional = tuple(operands[:split])
    kw_values = tuple(zip(names, operands[split:]))
    return dispatch_method_call(name.value, receiver, positional, kw_values, site, None)


_NATIVE_OPERATION_PROJECTORS = {
    # Receiver-selected method call (formal receiver or operand).
    "method_call": _project_method_call,
    # Unary / adapter Floor methods.
    "truth": lambda value, site: value.truth(site),
    "boolop_truth": lambda value, site: value.boolop_truth(site),
    "unary_truth": lambda value, unit, site: value.unary_truth(unit, site),
    # Formal arithmetic / bitwise unary (``-x`` / ``+x`` / ``~x``).
    # Production mints from SymbolicValue when formal_coordinate is present;
    # ground TermValue folds on the free Floor methods these projectors call.
    "unary_minus": _project_unary_minus,
    "unary_plus": _project_unary_plus,
    "bitwise_invert": _project_bitwise_invert,
    "attribute_named": lambda receiver, name, site: receiver.attribute_named(
        name, site
    ),
    # Formal subscript load (#6611): receiver[index] — binary, not the store.
    "subscript": lambda receiver, index, site: receiver.subscript(index, site),
    # Binary arithmetic / bitwise (_BINARY_OPERATOR_COORDINATE keys).
    "add": lambda left, right, site: left.add(right, site),
    "subtract": lambda left, right, site: left.subtract(right, site),
    "multiply": lambda left, right, site: left.multiply(right, site),
    "divide": lambda left, right, site: left.divide(right, site),
    "floor_divide": lambda left, right, site: left.floor_divide(right, site),
    "modulo": lambda left, right, site: left.modulo(right, site),
    "power": lambda left, right, site: left.power(right, site),
    "matrix_multiply": lambda left, right, site: left.matrix_multiply(right, site),
    "bitwise_and": lambda left, right, site: left.bitwise_and(right, site),
    "bitwise_or": lambda left, right, site: left.bitwise_or(right, site),
    "bitwise_xor": lambda left, right, site: left.bitwise_xor(right, site),
    "left_shift": lambda left, right, site: left.left_shift(right, site),
    "right_shift": lambda left, right, site: left.right_shift(right, site),
    # Authenticated in-place (AugAssign); binary fallback is inside each projector.
    **_INPLACE_NATIVE_OPERATION_PROJECTORS,
    # Equality, ordering, membership (compare / equality sugars).
    "equals": lambda left, right, site: left.equals(right, site),
    "less_than": lambda left, right, site: left.less_than(right, site),
    "less_equal": lambda left, right, site: left.less_equal(right, site),
    "greater_than": lambda left, right, site: left.greater_than(right, site),
    "greater_equal": lambda left, right, site: left.greater_equal(right, site),
    "contains": lambda container, item, site: container.contains(item, site),
    # Ternary store protocol (receiver, index|name, value + site).
    # Discharge order: receiver, index, value — never RHS-first.
    "setitem": lambda receiver, index, value, site: receiver.setitem(
        index, value, site
    ),
    # Attribute store: name arrives as StringValue; unwrap with .value.
    # Window 17534 mints operator="setattr_named" with operands
    # (receiver, StringValue(name), value).
    "setattr_named": lambda receiver, name, value, site: receiver.setattr(
        name.value, value, site
    ),
    # Binary delete protocol — explicit projectors (Python protocol signatures).
    "delitem": _project_delitem,
    "delattr_named": _project_delattr_named,
}


def _native_operation_projector_arity(projector) -> int:
    """Operand count named by an explicit projector (site is always last).

    A projector whose trailing parameter is variadic (``method_call``'s
    arguments, then the site) names its minimum: the fixed operands."""
    import inspect

    return len(inspect.signature(projector).parameters) - 1


def _native_operation_projector_is_variadic(projector) -> bool:
    import inspect

    parameters = tuple(inspect.signature(projector).parameters.values())
    return bool(parameters) and parameters[-1].kind is inspect.Parameter.VAR_POSITIONAL


def _conjoin_guards(guards):
    guards = tuple(guards)
    if not guards:
        return None
    if len(guards) == 1:
        return guards[0]
    from sugar_lift_py_tests.ir import and_

    return and_(list(guards))


_PRE_EFFECT_STATE_UNSET = object()


@dataclass(frozen=True)
class NativeOperationExitCarrierV1:
    """Deferred native operation whose discharge codomain is an ``ExitSet``.

    The same recorded operation can complete or raise after its formal operands
    are replaced by authenticated caller actuals.  Keeping that codomain here,
    rather than retaining a ``FloorValue``, is what preserves the exceptional
    arm until an enclosing effect boundary consumes it.

    Discharge routes through :data:`_NATIVE_OPERATION_PROJECTORS`: each operator
    names its Floor signature explicitly so n-ary stores (``setitem``,
    ``setattr_named``) are first-class, and a missing projector stays
    undischarged rather than panicking.
    """

    demand: NativeOperationDemandV1
    operands: tuple[FloorValue, ...]
    coordinates: tuple[object | None, ...]
    site: object = dataclass_field(compare=False, repr=False)
    continuations: tuple = dataclass_field(default=(), compare=False, repr=False)
    guards: tuple = dataclass_field(default=(), repr=False)
    prefix_composition: object | None = dataclass_field(
        default=None, compare=False, repr=False
    )
    exitset_continuations: tuple = dataclass_field(
        default=(), compare=False, repr=False
    )
    short_circuits: tuple = dataclass_field(default=(), compare=False, repr=False)
    # Where each short circuit was recorded: ``(continuations, exitset
    # continuations, guards)`` counts at that moment. Work enrolled after a
    # short circuit consumes the whole expression, so it runs on both legs.
    short_circuit_positions: tuple = dataclass_field(
        default=(), compare=False, repr=False
    )
    pre_effect_state: ReducerPreEffectStateV1 | None = dataclass_field(
        default=None, compare=False, repr=False
    )

    def __post_init__(self):
        operand_count = len(self.operands)
        coordinate_count = len(self.coordinates)
        demand_count = len(self.demand.operand_coordinate_cids)
        if len({operand_count, coordinate_count, demand_count}) != 1:
            from sugar_lift_py_tests.gap.info import GapKind
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="NativeOperationExitCarrierV1.__post_init__",
                blame=self.demand.source_node,
                observed=(operand_count, coordinate_count, demand_count),
                requested="one authenticated coordinate slot per ordered operand",
                fix="rebuild the carrier with aligned operands and coordinates",
                gap_kind=GapKind.FLOOR,
            )
        stored_cids = tuple(
            None if coordinate is None else coordinate.coordinate_cid
            for coordinate in self.coordinates
        )
        if stored_cids != self.demand.operand_coordinate_cids:
            from sugar_lift_py_tests.gap.info import GapKind
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="NativeOperationExitCarrierV1.__post_init__",
                blame=self.demand.source_node,
                observed=(stored_cids, self.demand.operand_coordinate_cids),
                requested="stored coordinates authenticating to the demand CID tuple",
                fix="preserve ordered coordinate identity when constructing the carrier",
                gap_kind=GapKind.FLOOR,
            )

    @classmethod
    def mint(cls, *, site, operator, operands, coordinates):
        operands = tuple(operands)
        coordinates = tuple(coordinates)
        return cls(
            demand=NativeOperationDemandV1.mint(
                site=site,
                operator=operator,
                operands=operands,
                coordinates=coordinates,
            ),
            operands=operands,
            coordinates=coordinates,
            site=site,
        )

    def _enroll_pre_effect_state(self, pre_effect_state):
        """Enroll reducer testimony without adding an expression continuation."""
        testimony = self.pre_effect_state
        if pre_effect_state is not _PRE_EFFECT_STATE_UNSET:
            if not isinstance(pre_effect_state, ReducerPreEffectStateV1):
                raise TypeError(
                    "pre_effect_state must be reducer-issued testimony; raw "
                    f"{type(pre_effect_state).__name__} is not admissible"
                )
            if testimony is not None and testimony.state != pre_effect_state.state:
                from sugar_lift_py_tests.gap.info import GapKind
                from sugar_lift_py_tests.gap.panic import construction_panic_gap

                construction_panic_gap(
                    owner="NativeOperationExitCarrierV1.and_then",
                    blame=self.demand.source_node,
                    observed="a second conflicting reducer pre-effect state",
                    requested="one reducer enrollment carrying one exact state",
                    fix=(
                        "enroll the carrier once at reduce_block_to_exitset; "
                        "later expression continuations must omit pre_effect_state"
                    ),
                    gap_kind=GapKind.FLOOR,
                )
            if testimony is None:
                testimony = pre_effect_state
        return replace(self, pre_effect_state=testimony)

    def and_then(self, step, *, pre_effect_state=_PRE_EFFECT_STATE_UNSET):
        """Retain work and, at the reducer seam, the exact pre-effect state."""
        enrolled = self._enroll_pre_effect_state(pre_effect_state)
        return replace(
            enrolled,
            continuations=(*enrolled.continuations, step),
        )

    def guarded(self, guard, face=None):
        """Guard the deferred operation without discharging or losing its demand."""
        del face
        return replace(self, guards=(*self.guards, guard))

    def after_discharge(self, step) -> "NativeOperationExitCarrierV1":
        """Defer an ExitSet-wide consumer until authenticated discharge."""
        return replace(
            self,
            exitset_continuations=(
                *self.exitset_continuations,
                (len(self.continuations), step),
            ),
        )

    @classmethod
    def compose_prefix(cls, prefix, step):
        """Sequence a prefix without exposing a deferred carrier to ExitSet.

        Each completed prefix arm retains its own carrier instance because its
        continuations and pre-effect state belong to that arm.  Halted and
        already-resolved arms are retained verbatim.  Compatible carrier arms
        share one authenticated demand; different demands are not mergeable.
        """
        from sugar_lift_py_tests.outcome import ExitSet, Halted
        from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset

        resolved = []
        deferred = []
        for prefix_exit in prefix.exits:
            if isinstance(prefix_exit, Halted):
                resolved.append(prefix_exit)
                continue
            following = step(prefix_exit.value)
            if isinstance(following, cls):
                deferred.append((prefix_exit, following))
                continue
            if not isinstance(following, ExitSet):
                following = outcome_to_exitset(following)
            sequenced = ExitSet((prefix_exit,)).sequence(
                lambda _value, *, exits=following: exits
            )
            resolved.extend(sequenced.exits)

        if not deferred:
            return ExitSet(tuple(resolved)).normalize()

        demand_cids = {carrier.demand.demand_cid for _, carrier in deferred}
        if len(demand_cids) != 1:
            from sugar_lift_py_tests.gap.info import GapKind
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="NativeOperationExitCarrierV1.compose_prefix",
                blame=tuple(sorted(demand_cids)),
                observed="incompatible native-operation demands beneath one prefix",
                requested="one authenticated demand shared by every deferred prefix arm",
                fix="keep distinct native-operation demands in separate control-flow joins",
                gap_kind=GapKind.FLOOR,
            )

        representative = deferred[0][1]
        return replace(
            representative,
            prefix_composition=(
                tuple(resolved),
                tuple(deferred),
                len(representative.continuations),
                len(representative.guards),
                len(representative.exitset_continuations),
            ),
        )

    def short_circuit(
        self,
        *,
        continuing_guard: Formula,
        stopped: "ExitSet",
        continuing_face,
        stopped_face,
    ) -> "NativeOperationExitCarrierV1":
        """Retain this deferred leg beside an already-decided stopping face.

        Compare owns the carrier's operation site and therefore its eventual
        occurrence.  This composition records only control-flow testimony; it
        never rebuilds the operation or manufactures an occurrence.
        """
        from sugar_lift_py_tests.outcome import ExitSet

        if not isinstance(stopped, ExitSet):
            raise TypeError("short-circuit stopping face must be an ExitSet")
        return replace(
            self,
            short_circuits=(
                *self.short_circuits,
                (continuing_guard, stopped, continuing_face, stopped_face),
            ),
            short_circuit_positions=(
                *self._short_circuit_positions(),
                (
                    len(self.continuations),
                    len(self.exitset_continuations),
                    len(self.guards),
                ),
            ),
        )

    def _short_circuit_positions(self):
        """One recorded position per short circuit (unrecorded: at the end)."""
        end = (
            len(self.continuations),
            len(self.exitset_continuations),
            len(self.guards),
        )
        known = tuple(self.short_circuit_positions)
        return known + (end,) * (len(self.short_circuits) - len(known))

    def discharge(self, actuals_by_formal_coordinate):
        """Evaluate against authenticated actual operands and project exits.

        Coordinate-length and coordinate-identity invariants are owned by
        :meth:`__post_init__` (#6613).  Missing authenticated evidence, an
        operator absent from the projector table, and projector arity mismatch
        remain undischarged — never a construction panic.
        """
        from sugar_lift_py_tests.effect import RaiseEffect
        from sugar_lift_py_tests.outcome import (
            Complete,
            ExitSet,
            Halted,
            Incomplete,
            true_guard,
        )
        from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset

        def apply_exitset_step(projected, step):
            projected = step(projected)
            if isinstance(projected, NativeOperationExitCarrierV1):
                projected = projected.discharge(actuals_by_formal_coordinate)
            if not isinstance(projected, ExitSet):
                projected = outcome_to_exitset(projected)
            return projected

        def apply_exitset_steps(projected, continuation_count):
            for enrolled_count, step in self.exitset_continuations:
                if enrolled_count != continuation_count:
                    continue
                projected = apply_exitset_step(projected, step)
            return projected

        if self.prefix_composition is not None:
            (
                resolved,
                deferred,
                continuation_count,
                guard_count,
                exitset_count,
            ) = self.prefix_composition
            exits = list(resolved)
            for prefix_exit, carrier in deferred:
                following = carrier.discharge(actuals_by_formal_coordinate)
                sequenced = ExitSet((prefix_exit,)).sequence(
                    lambda _value, *, result=following: result
                )
                exits.extend(sequenced.exits)
            # Do not normalize across prefix arms: each arm's partition faces,
            # obligations, and temporal state remain independently testified.
            projected = ExitSet(tuple(exits))
            for continuation in self.continuations[continuation_count:]:
                projected = type(self).compose_prefix(projected, continuation)
                if isinstance(projected, NativeOperationExitCarrierV1):
                    projected = projected.discharge(actuals_by_formal_coordinate)
            guard = _conjoin_guards(self.guards[guard_count:])
            if guard is not None:
                projected = projected.guarded(guard)
            # Only steps enrolled after the prefix: the deferred arms'
            # carriers already ran their own when they discharged.
            for _enrolled_count, step in self.exitset_continuations[exitset_count:]:
                projected = apply_exitset_step(projected, step)
            return projected

        def undischarged(reason):
            return NativeOperationResolutionV1.undischarged(reason).project(
                source_node=self.demand.source_node
            )

        actual_operands = []
        for original, coordinate_cid in zip(
            self.operands, self.demand.operand_coordinate_cids, strict=True
        ):
            if coordinate_cid is None:
                actual_operands.append(original)
                continue
            if coordinate_cid not in actuals_by_formal_coordinate:
                return undischarged(
                    "authenticated caller actual absent for " f"{coordinate_cid}"
                )
            actual_operands.append(actuals_by_formal_coordinate[coordinate_cid])

        projector = _NATIVE_OPERATION_PROJECTORS.get(self.demand.operator)
        if projector is None:
            return undischarged(
                "native operation projector unavailable for operator "
                f"{self.demand.operator!r}"
            )

        expected_arity = _native_operation_projector_arity(projector)
        if (
            len(actual_operands) < expected_arity
            if _native_operation_projector_is_variadic(projector)
            else len(actual_operands) != expected_arity
        ):
            return undischarged(
                "native operation arity is unavailable for projector "
                f"{self.demand.operator!r} "
                f"(arity={len(actual_operands)}, expected={expected_arity})"
            )

        # Bind by the projector's declared parameter order.  Each lambda names
        # its Floor signature; this is not a generic method splat.
        projected = projector(*actual_operands, self.site)
        if (
            isinstance(projected, Incomplete)
            and isinstance(projected.effect, RaiseEffect)
            and not projected.branch_conditions
        ):
            # A decided raise: the halt carries the exception identity and
            # the occurrence the exceptional resolution cites.
            effect = projected.effect
            if effect.exception_type_coordinate is None or effect.occurrence_id is None:
                resolution = NativeOperationResolutionV1.undischarged(
                    "native operation exception identity unproven"
                )
            else:
                resolution = NativeOperationResolutionV1.exceptional(
                    exception_type_coordinate=effect.exception_type_coordinate,
                    operation_occurrence=self.demand.source_node,
                    effect=effect,
                    pre_effect_state=self.pre_effect_state,
                )
            exits = resolution.project(source_node=self.demand.source_node)
        elif isinstance(projected, Complete):
            exits = NativeOperationResolutionV1.completed(projected.value).project(
                source_node=self.demand.source_node
            )
        elif isinstance(projected, Incomplete):
            exits = NativeOperationResolutionV1.undischarged(projected.reason).project(
                source_node=self.demand.source_node
            )
        elif isinstance(projected, ExitSet):
            exits = projected
        else:
            # Other Outcome variants must pass through the exit algebra's loud
            # door.  In particular, never reinterpret an unresolved carrier as
            # a normal completion.
            exits = outcome_to_exitset(projected)

        # A short circuit recorded before later work (``return a if c else
        # -x``: the return, the block projection, an enclosing ``if``'s join)
        # unions its stopping face in where it was recorded, so that work runs
        # on both legs. One recorded after all work keeps the end-of-discharge
        # union below.
        end = (
            len(self.continuations),
            len(self.exitset_continuations),
            len(self.guards),
        )
        positions = self._short_circuit_positions()
        positional = [
            (position, short)
            for position, short in zip(positions, self.short_circuits)
            if position != end
        ]
        trailing = [
            short
            for position, short in zip(positions, self.short_circuits)
            if position == end
        ]
        guards_applied = 0

        def union_short_circuit(exits, short):
            continuing_guard, stopped, continuing_face, stopped_face = short
            stopping_exits = []
            for exit_ in stopped.exits:
                if isinstance(exit_, Halted):
                    # A first-leg exception predates the truth-value split and
                    # bypasses both faces unchanged.
                    stopping_exits.append(exit_)
                    continue
                stopping_exits.extend(
                    ExitSet((exit_,)).guarded(true_guard(), stopped_face).exits
                )
            return exits.guarded(continuing_guard, continuing_face).union(
                ExitSet(tuple(stopping_exits))
            )

        def at_point(exits, continuation_count):
            # Exit-set steps and short circuits enrolled at this continuation
            # count, in the order they were enrolled.
            nonlocal guards_applied
            events = [
                (index, 1, step)
                for index, (enrolled_count, step) in enumerate(
                    self.exitset_continuations
                )
                if enrolled_count == continuation_count
            ]
            events.extend(
                (exitset_count, 0, (guard_count, short))
                for (count, exitset_count, guard_count), short in positional
                if count == continuation_count
            )
            for _order, kind, event in sorted(events, key=lambda e: (e[0], e[1])):
                if kind == 1:
                    exits = apply_exitset_step(exits, event)
                    continue
                guard_count, short = event
                pre_split = _conjoin_guards(self.guards[guards_applied:guard_count])
                if pre_split is not None:
                    exits = exits.guarded(pre_split)
                guards_applied = max(guards_applied, guard_count)
                exits = union_short_circuit(exits, short)
            return exits

        step_point = at_point if positional else apply_exitset_steps

        exits = step_point(exits, 0)
        for index, continuation in enumerate(self.continuations, start=1):

            def resume(value, *, step=continuation):
                next_outcome = step(value)
                if isinstance(next_outcome, NativeOperationExitCarrierV1):
                    # A reducer continuation can mint a later carrier with the
                    # state reached after this operation completed. Preserve
                    # that newer reducer-issued testimony; inherit ours only
                    # when the nested carrier has no state of its own.
                    if (
                        self.pre_effect_state is not None
                        and next_outcome.pre_effect_state is None
                    ):
                        next_outcome = next_outcome._enroll_pre_effect_state(
                            self.pre_effect_state
                        )
                    return next_outcome.discharge(actuals_by_formal_coordinate)
                return next_outcome

            exits = exits.and_then(resume)
            exits = step_point(exits, index)
        guard = _conjoin_guards(self.guards[guards_applied:])
        if guard is not None:
            exits = exits.guarded(guard)
        for short in trailing:
            exits = union_short_circuit(exits, short)
        return exits


@dataclass(frozen=True)
class ValueOccurrenceCoordinateV1:
    source: SourceFragmentCoordinateV1
    occurrence_cid: str

    @classmethod
    def mint(cls, source):
        return cls(source, _cid({"kind": "value-occurrence", "source": source.wire()}))

    def to_value(self):
        return {"source": self.source.wire(), "occurrenceCid": self.occurrence_cid}

    @classmethod
    def from_value(cls, value):
        if not isinstance(value, dict) or set(value) != {"source", "occurrenceCid"}:
            raise ValueError("value occurrence requires an exact key set")
        result = cls(
            SourceFragmentCoordinateV1.decode(value["source"]),
            value["occurrenceCid"],
        )
        if result != cls.mint(result.source):
            raise ValueError("value occurrence CID is stale")
        return result


@dataclass(frozen=True)
class FormalActualBindingV1:
    formal_coordinate_cid: str
    actual_occurrence: ValueOccurrenceCoordinateV1
    actual_term: Term
    actual_contract_ref_cid: str | None = None

    def to_value(self):
        return {
            "formalCoordinateCid": self.formal_coordinate_cid,
            "actualOccurrence": self.actual_occurrence.to_value(),
            "actualTerm": _json(term_to_value(self.actual_term)),
            "actualContractRefCid": self.actual_contract_ref_cid,
        }

    @classmethod
    def from_value(cls, value):
        expected = {
            "formalCoordinateCid",
            "actualOccurrence",
            "actualTerm",
            "actualContractRefCid",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("formal actual binding requires an exact key set")
        return cls(
            value["formalCoordinateCid"],
            ValueOccurrenceCoordinateV1.from_value(value["actualOccurrence"]),
            _term_from_value(value["actualTerm"]),
            value["actualContractRefCid"],
        )


@dataclass(frozen=True)
class CallEdgeV2:
    source_contract_cid: str
    target_contract_cid: str
    call_site: SourceFragmentCoordinateV1
    formal_actual_bindings: tuple[FormalActualBindingV1, ...]
    edge_cid: str

    @classmethod
    def mint(
        cls,
        *,
        source_contract_cid,
        target_contract_cid,
        call_site,
        formal_actual_bindings,
    ):
        bindings = tuple(formal_actual_bindings)
        coordinates = tuple(item.formal_coordinate_cid for item in bindings)
        if len(coordinates) != len(set(coordinates)):
            raise ValueError("CallEdgeV2 has a duplicate formal coordinate")
        preimage = {
            "kind": "call-edge",
            "schemaVersion": "2",
            "sourceContractCid": source_contract_cid,
            "targetContractCid": target_contract_cid,
            "callSite": call_site.wire(),
            "formalActualBindings": [item.to_value() for item in bindings],
        }
        return cls(
            source_contract_cid,
            target_contract_cid,
            call_site,
            bindings,
            _cid(preimage),
        )

    def to_value(self):
        return {
            "kind": "call-edge",
            "schemaVersion": "2",
            "sourceContractCid": self.source_contract_cid,
            "targetContractCid": self.target_contract_cid,
            "callSite": self.call_site.wire(),
            "formalActualBindings": [
                item.to_value() for item in self.formal_actual_bindings
            ],
            "edgeCid": self.edge_cid,
        }

    @classmethod
    def from_value(cls, value):
        expected = {
            "kind",
            "schemaVersion",
            "sourceContractCid",
            "targetContractCid",
            "callSite",
            "formalActualBindings",
            "edgeCid",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("CallEdgeV2 requires an exact key set")
        result = cls.mint(
            source_contract_cid=value["sourceContractCid"],
            target_contract_cid=value["targetContractCid"],
            call_site=SourceFragmentCoordinateV1.decode(value["callSite"]),
            formal_actual_bindings=tuple(
                FormalActualBindingV1.from_value(item)
                for item in value["formalActualBindings"]
            ),
        )
        if (
            value["kind"] != "call-edge"
            or value["schemaVersion"] != "2"
            or result.edge_cid != value["edgeCid"]
        ):
            raise ValueError("CallEdgeV2 CID is stale")
        return result


def _term_from_value(value):
    from sugar_lift_py_tests.ir import (
        bool_const,
        ctor,
        make_var,
        num,
        real_lit,
        str_const,
    )

    if not isinstance(value, dict):
        raise ValueError("actual term must be a ProofIR term")
    if value.get("kind") == "var" and set(value) == {"kind", "name"}:
        return make_var(value["name"])
    if value.get("kind") == "ctor" and set(value) == {"kind", "name", "args"}:
        return ctor(value["name"], [_term_from_value(item) for item in value["args"]])
    if value.get("kind") == "const" and set(value) == {"kind", "value", "sort"}:
        sort = value["sort"].get("name") if isinstance(value["sort"], dict) else None
        if sort == "Int" and type(value["value"]) is int:
            return num(value["value"])
        if sort == "Bool" and type(value["value"]) is bool:
            return bool_const(value["value"])
        if sort == "String" and isinstance(value["value"], str):
            return str_const(value["value"])
        if sort == "Real" and isinstance(value["value"], str):
            return real_lit(value["value"])
    raise ValueError("actual term shape is unsupported")


# --- Phase 1/2/3 continuation schema (mirrors sugar-linker/src/caller_parameter.rs) ---


@dataclass(frozen=True)
class ParameterOwnedContractV1:
    """The callee's structural identity: its formals + the demands it
    STRUCTURALLY OWNS, independent of any post projection. `semantic_decl` is a
    contract declaration whose JCS CID is `contract_cid`; the four ownership
    sub-fields are re-derived byte-for-byte by Rust `ParameterOwnedContractV1::
    validate` against the sibling fields."""

    contract_cid: str
    semantic_decl: Any
    owner_source_identity_cid: str
    owner_definition_locus: SourceFragmentCoordinateV1
    formal_coordinates: tuple
    formal_sorts: tuple
    declared_demand_cids: tuple

    @classmethod
    def mint(
        cls,
        *,
        name: str,
        owner_source_identity_cid: str,
        owner_definition_locus: SourceFragmentCoordinateV1,
        formal_coordinates: tuple,
        declared_demand_cids,
    ) -> "ParameterOwnedContractV1":
        from sugar_lift_py_tests.ir import ContractDecl, contract_decl_to_value

        coords = tuple(formal_coordinates)
        # Rust BTreeSet<Cid>: sorted, de-duplicated.
        declared = tuple(sorted(set(declared_demand_cids)))
        formal_declarations = [
            {"coordinate": coordinate.to_value()} for coordinate in coords
        ]
        decl = ContractDecl(
            name=name,
            owner_source_identity_cid=owner_source_identity_cid,
            owner_definition_locus=owner_definition_locus.wire(),
            formal_declarations=formal_declarations,
            declared_parameter_demand_cids=list(declared),
        )
        semantic_decl = _json(contract_decl_to_value(decl))
        return cls(
            contract_cid=_cid(semantic_decl),
            semantic_decl=semantic_decl,
            owner_source_identity_cid=owner_source_identity_cid,
            owner_definition_locus=owner_definition_locus,
            formal_coordinates=coords,
            formal_sorts=tuple(coordinate.sort for coordinate in coords),
            declared_demand_cids=declared,
        )

    def to_value(self) -> dict[str, Any]:
        return {
            "contractCid": self.contract_cid,
            "semanticDecl": self.semantic_decl,
            "ownerSourceIdentityCid": self.owner_source_identity_cid,
            "ownerDefinitionLocus": self.owner_definition_locus.wire(),
            "formalDeclarations": [
                {"coordinate": coordinate.to_value()}
                for coordinate in self.formal_coordinates
            ],
            "formalSorts": [
                {"kind": "primitive", "name": sort.name} for sort in self.formal_sorts
            ],
            "declaredDemandCids": list(self.declared_demand_cids),
        }


@dataclass(frozen=True)
class ParameterContractLinkUnitV1:
    """One function's closed enrollment row: its owned contract, its candidates
    (none: nothing in the lift owes a parameter contract, inventory item 43),
    the already-constructed call edges, and the retained continuation key
    `link_unit_cid`."""

    source_memento: Any
    parameter_owned_contract: ParameterOwnedContractV1
    candidates: tuple
    call_edges: tuple
    link_unit_cid: str

    @classmethod
    def mint(cls, *, source_memento, parameter_owned_contract, candidates, call_edges):
        cands = tuple(candidates)
        edges = tuple(call_edges)
        preimage = {
            "kind": "parameter-contract-link-unit",
            "schemaVersion": "1",
            "sourceMemento": source_memento,
            "parameterOwnedContract": parameter_owned_contract.to_value(),
            "candidates": [candidate.to_value() for candidate in cands],
            "callEdges": [edge.to_value() for edge in edges],
        }
        return cls(
            source_memento, parameter_owned_contract, cands, edges, _cid(preimage)
        )

    def to_value(self) -> dict[str, Any]:
        return {
            "kind": "parameter-contract-link-unit",
            "schemaVersion": "1",
            "sourceMemento": self.source_memento,
            "parameterOwnedContract": self.parameter_owned_contract.to_value(),
            "candidates": [candidate.to_value() for candidate in self.candidates],
            "callEdges": [edge.to_value() for edge in self.call_edges],
            "linkUnitCid": self.link_unit_cid,
        }


@dataclass(frozen=True)
class ParameterContractResolutionSetV1:
    """The Phase-2 fold's authenticated verdict set, bound to the continuation
    it discharges. `set_cid` mutually binds `link_unit_cid` (the replay guard):
    a resume accepts a set ONLY when both CIDs agree with the retained
    continuation."""

    link_unit_cid: str
    resolutions: tuple
    set_cid: str

    @classmethod
    def mint(cls, *, link_unit_cid: str, resolutions):
        rows = tuple(resolutions)
        preimage = {
            "kind": "parameter-contract-resolution-set",
            "schemaVersion": "1",
            "linkUnitCid": link_unit_cid,
            "resolutions": list(rows),
        }
        return cls(link_unit_cid, rows, _cid(preimage))

    @classmethod
    def from_value(cls, value) -> "ParameterContractResolutionSetV1":
        expected = {"kind", "schemaVersion", "linkUnitCid", "resolutions", "setCid"}
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("resolution set requires an exact key set")
        result = cls.mint(
            link_unit_cid=value["linkUnitCid"],
            resolutions=tuple(value["resolutions"]),
        )
        if (
            value["kind"] != "parameter-contract-resolution-set"
            or value["schemaVersion"] != "1"
            or result.set_cid != value["setCid"]
        ):
            raise ValueError("resolution set CID is stale")
        return result

    def to_value(self) -> dict[str, Any]:
        return {
            "kind": "parameter-contract-resolution-set",
            "schemaVersion": "1",
            "linkUnitCid": self.link_unit_cid,
            "resolutions": list(self.resolutions),
            "setCid": self.set_cid,
        }


class ResumeStalePanic(Exception):
    """A resume that could not be honored: loud, never a silent reconstruction."""


def _resolution_preimage(resolution: dict) -> dict:
    return {
        "kind": resolution["kind"],
        "schemaVersion": resolution["schemaVersion"],
        "demandCid": resolution["demandCid"],
        "candidateCid": resolution["candidateCid"],
        "contractCid": resolution["contractCid"],
        "basis": resolution["basis"],
        "callerUniverseCid": resolution["callerUniverseCid"],
    }


def _validate_resolution(resolution: dict) -> None:
    expected = {
        "kind",
        "schemaVersion",
        "demandCid",
        "candidateCid",
        "contractCid",
        "basis",
        "callerUniverseCid",
        "resolutionCid",
    }
    if not isinstance(resolution, dict) or set(resolution) != expected:
        raise ResumeStalePanic("resolution requires an exact key set")
    if (
        resolution["kind"] != "parameter-contract-resolution"
        or resolution["schemaVersion"] != "1"
        or _cid(_resolution_preimage(resolution)) != resolution["resolutionCid"]
    ):
        raise ResumeStalePanic("resolution CID is stale")
    basis = resolution["basis"]
    if basis == "declared-demand":
        if resolution["callerUniverseCid"] is not None:
            raise ResumeStalePanic(
                "declared-demand resolution carries a caller universe"
            )
    elif basis == "closed-callers":
        if resolution["callerUniverseCid"] is None:
            raise ResumeStalePanic("closed-callers resolution lacks a caller universe")
    else:
        raise ResumeStalePanic("resolution basis is unknown")


def resume_apply_resolutions(link_unit, resolution_set) -> dict[str, dict]:
    """The Phase-3 resume decision. Given the RETAINED link unit (the immutable
    continuation) and the presented resolution set, honor the resume ONLY when
    the set is bound to THIS continuation (the replay guard:
    resolution_set.link_unit_cid == link_unit.link_unit_cid, and set_cid
    re-derives, checked by ParameterContractResolutionSetV1.from_value) and
    names no demand: a link unit owes no candidate (inventory item 43), so every
    presented resolution is foreign. Each one is validated first, so a stale
    CID is named as stale.

    Returns ``{}`` on success; raises ResumeStalePanic (which the caller lifts to
    a ConstructionPanic) otherwise. Never reconstructs.
    """
    if resolution_set.link_unit_cid != link_unit.link_unit_cid:
        raise ResumeStalePanic(
            "resolution set is bound to a different continuation "
            f"({resolution_set.link_unit_cid} != {link_unit.link_unit_cid})"
        )
    for resolution in resolution_set.resolutions:
        _validate_resolution(resolution)
        raise ResumeStalePanic(
            f"resolution for a foreign demand {resolution['demandCid']}"
        )
    return {}
