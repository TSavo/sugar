from __future__ import annotations

import pytest

from dataclasses import dataclass, replace

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    NativeOperationResolutionV1,
    _NATIVE_OPERATION_PROJECTORS,
    authenticated_exceptional_resolution_count,
    production_native_operation_operators,
    source_coordinate,
)
from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import (
    FloorValue,
    ListValue,
    NoneValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import PrimitiveSort, atomic, ctor, make_var, str_const
from sugar_lift_py_tests.outcome import (
    Complete,
    Completed,
    ExitSet,
    Halted,
    outcome_to_exitset,
    true_guard,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _site():
    source = "def operation(left, right):\n    return left + right\n"
    tree = SourceFile(
        (source, "native_operation.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(tree.functions()).fragment


def _coordinate(name: str, ordinal: int) -> FormalParameterCoordinateV1:
    source_cid = "blake3-512:" + "a" * 128
    owner = SourceFragmentCoordinateV1(source_cid, 1, 0, 2, 23)
    return FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=source_cid,
        owner_definition_locus=owner,
        declaration_locus=SourceFragmentCoordinateV1(
            source_cid, 1, 14 + ordinal * 6, 1, 18 + ordinal * 6
        ),
        ordinal=ordinal,
        parameter_kind="positional-or-keyword",
        declared_name=name,
        sort=PrimitiveSort("Value"),
    )


def _carrier(operator: str = "add"):
    left_coordinate = _coordinate("left", 0)
    right_coordinate = _coordinate("right", 1)
    carrier = NativeOperationExitCarrierV1.mint(
        site=_site(),
        operator=operator,
        operands=(
            SymbolicValue(make_var("left"), left_coordinate),
            SymbolicValue(make_var("right"), right_coordinate),
        ),
        coordinates=(left_coordinate, right_coordinate),
    )
    return carrier, left_coordinate, right_coordinate


@pytest.mark.parametrize(
    ("method", "operator"),
    (
        ("add", "add"),
        ("subtract", "subtract"),
        ("multiply", "multiply"),
        ("divide", "divide"),
        ("floor_divide", "floor_divide"),
        ("modulo", "modulo"),
        ("power", "power"),
        ("matrix_multiply", "matrix_multiply"),
        ("bitwise_and", "bitwise_and"),
        ("bitwise_or", "bitwise_or"),
        ("bitwise_xor", "bitwise_xor"),
        ("left_shift", "left_shift"),
        ("right_shift", "right_shift"),
    ),
)
def test_formal_binary_dispatch_mints_caller_discharge_carrier(method, operator):
    left_coordinate = _coordinate("left", 0)
    right_coordinate = _coordinate("right", 1)
    left = SymbolicValue(make_var("left"), left_coordinate)
    right = SymbolicValue(make_var("right"), right_coordinate)

    outcome = getattr(left, method)(right, _site())

    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.demand.operator == operator
    assert outcome.operands == (left, right)
    assert outcome.demand.operand_coordinate_cids == (
        left_coordinate.coordinate_cid,
        right_coordinate.coordinate_cid,
    )


def test_swapped_formal_binary_operands_retain_distinct_ordered_demands():
    left_coordinate = _coordinate("left", 0)
    right_coordinate = _coordinate("right", 1)
    left = SymbolicValue(make_var("left"), left_coordinate)
    right = SymbolicValue(make_var("right"), right_coordinate)

    forward = left.subtract(right, _site())
    reverse = right.subtract(left, _site())

    assert isinstance(forward, NativeOperationExitCarrierV1)
    assert isinstance(reverse, NativeOperationExitCarrierV1)
    assert forward.demand.operator == reverse.demand.operator == "subtract"
    assert forward.demand.operand_coordinate_cids == (
        left_coordinate.coordinate_cid,
        right_coordinate.coordinate_cid,
    )
    assert reverse.demand.operand_coordinate_cids == (
        right_coordinate.coordinate_cid,
        left_coordinate.coordinate_cid,
    )
    assert forward.demand.demand_cid != reverse.demand.demand_cid


@pytest.mark.parametrize("formal_side", ("left", "right"))
def test_either_formal_operand_is_enough_to_defer_binary_dispatch(formal_side):
    coordinate = _coordinate(formal_side, 0)
    left = SymbolicValue(
        make_var("left"), coordinate if formal_side == "left" else None
    )
    right = SymbolicValue(
        make_var("right"), coordinate if formal_side == "right" else None
    )

    outcome = left.add(right, _site())

    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.coordinates == (
        coordinate if formal_side == "left" else None,
        coordinate if formal_side == "right" else None,
    )


def test_coordinate_free_binary_dispatch_retains_existing_symbolic_faces():
    outcome = SymbolicValue(make_var("left")).add(
        SymbolicValue(make_var("right")), _site()
    )

    assert isinstance(outcome, ExitSet)
    assert (
        len(tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Completed)))
        == 1
    )
    assert (
        len(tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))) == 1
    )


def test_same_native_operation_demand_can_complete_for_authenticated_actuals():
    carrier, left, right = _carrier()

    exits = carrier.discharge(
        {
            left.coordinate_cid: TermValue(1),
            right.coordinate_cid: TermValue(2),
        }
    )

    assert exits.exits == (Completed(exits.exits[0].guard, TermValue(3)),)


def test_guard_preserves_carrier_demand_until_authenticated_discharge():
    carrier, left, right = _carrier()
    guarded = carrier.guarded(atomic("test.guard", []))
    assert isinstance(guarded, NativeOperationExitCarrierV1)
    assert guarded.demand == carrier.demand
    exits = guarded.discharge(
        {left.coordinate_cid: TermValue(1), right.coordinate_cid: TermValue(2)}
    )
    assert isinstance(exits.exits[0], Completed)
    assert exits.exits[0].guard is not None


def test_guarded_but_undischarged_carrier_cannot_report_completion():
    carrier, _, _ = _carrier()
    with pytest.raises(ConstructionPanic, match="native operation"):
        outcome_to_exitset(carrier.guarded(atomic("test.guard", [])))


def test_same_native_operation_demand_can_halt_for_authenticated_actuals():
    carrier, left, right = _carrier()

    exits = carrier.discharge(
        {
            left.coordinate_cid: NoneValue(),
            right.coordinate_cid: TermValue(2),
        }
    )

    assert len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_name is None
    assert halted.effect.exception_type_coordinate == _Expected("TypeError").identity
    assert halted.effect.occurrence is not None


def test_undischarged_native_operation_is_typed_loud_not_completed():
    carrier, _, _ = _carrier()

    with pytest.raises(ConstructionPanic, match="native operation"):
        outcome_to_exitset(carrier)


def test_missing_authenticated_actual_is_undischarged_not_a_construction_panic():
    carrier, left, _ = _carrier()

    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        carrier.discharge({left.coordinate_cid: TermValue(1)})


def test_unavailable_native_operation_is_undischarged_not_a_construction_panic():
    carrier, left, right = _carrier(operator="not_a_floor_operation")
    with pytest.raises(SugarNotWritten, match="projector unavailable"):
        carrier.discharge(
            {left.coordinate_cid: TermValue(1), right.coordinate_cid: TermValue(2)}
        )


def test_unsupported_native_arity_is_undischarged_not_a_construction_panic():
    # Three aligned operand/coordinate slots is a valid carrier shape (n-ary
    # stores use it).  Operator "add" has no ternary projector, so discharge
    # stays undischarged — not a construction panic.
    carrier, left, right = _carrier()
    third = left
    three = NativeOperationExitCarrierV1.mint(
        site=_site(),
        operator="add",
        operands=carrier.operands + (carrier.operands[0],),
        coordinates=(left, right, third),
    )
    with pytest.raises(SugarNotWritten, match="arity is unavailable"):
        three.discharge(
            {left.coordinate_cid: TermValue(1), right.coordinate_cid: TermValue(2)}
        )

    # Length mismatch is independently loud at construction (#6613).
    demand = replace(
        carrier.demand,
        operand_coordinate_cids=carrier.demand.operand_coordinate_cids
        + (left.coordinate_cid,),
    )
    with pytest.raises(ConstructionPanic, match="one authenticated coordinate slot"):
        replace(
            carrier,
            demand=demand,
        )


def test_same_length_swapped_coordinate_identities_panic_at_construction():
    carrier, left, right = _carrier()
    with pytest.raises(ConstructionPanic, match="ordered coordinate identity"):
        replace(carrier, coordinates=(right, left))


def test_swapped_operands_retain_distinct_demand_coordinates():
    carrier, left, right = _carrier()
    swapped = NativeOperationExitCarrierV1.mint(
        site=_site(),
        operator="add",
        operands=tuple(reversed(carrier.operands)),
        coordinates=(right, left),
    )

    assert carrier.demand.operand_coordinate_cids == (
        left.coordinate_cid,
        right.coordinate_cid,
    )
    assert swapped.demand.operand_coordinate_cids == (
        right.coordinate_cid,
        left.coordinate_cid,
    )
    assert carrier.demand.demand_cid != swapped.demand.demand_cid


class _Expected:
    def __init__(self, name: str):
        self.identity = ctor(
            "python:exception_type_identity",
            [str_const("builtins"), str_const(name)],
        )

    def exception_type_identity(self):
        return self.identity


def test_lying_exception_type_is_rejected_without_inventing_identity():
    carrier, left, right = _carrier()
    exits = carrier.discharge(
        {
            left.coordinate_cid: NoneValue(),
            right.coordinate_cid: TermValue(2),
        }
    )
    routed = exits.and_exit(
        type(exits).completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected("ValueError")),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )
    assert len(routed.exits) == 1
    assert isinstance(routed.exits[0], Halted)
    assert (
        routed.exits[0].effect.exception_type_coordinate
        != _Expected("ValueError").identity
    )


def test_identity_operation_never_acquires_a_fabricated_exceptional_edge():
    # Production identity comparisons do not mint a carrier today; equals on
    # two equal ground terms is the closest completed-only native discharge.
    carrier, left, right = _carrier("equals")

    exits = carrier.discharge(
        {
            left.coordinate_cid: TermValue(1),
            right.coordinate_cid: TermValue(1),
        }
    )

    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)


def test_nameless_resolution_is_undischarged_and_cannot_project_a_halt():
    resolution = NativeOperationResolutionV1.undischarged(
        "native operation exception identity unproven"
    )

    assert resolution.kind == "undischarged"
    assert not resolution.has_authenticated_exception_type
    with pytest.raises(SugarNotWritten, match="identity unproven"):
        resolution.project(source_node=_site())


def test_only_coordinate_authenticated_resolutions_count_as_exceptional_exits():
    source = _site()
    named = NativeOperationResolutionV1.exceptional(
        exception_type_coordinate=_Expected("TypeError").identity,
        operation_occurrence=source_coordinate(source),
    )
    nameless = NativeOperationResolutionV1.undischarged("identity unproven")
    completed = NativeOperationResolutionV1.completed(TermValue(1))

    assert authenticated_exceptional_resolution_count((named, nameless, completed)) == 1
    assert not nameless.is_authenticated_exceptional_exit


def test_nameless_halt_stays_outside_matching_boundary_end_to_end():
    body = ExitSet(
        (
            Halted(
                true_guard(),
                RaiseEffect(occurrence="operation-origin"),
            ),
        )
    )

    with pytest.raises(SugarNotWritten, match="no term to state the test over"):
        body.and_exit(
            ExitSet.completed(object()),
            disposition=EffectBoundaryDisposition(
                matcher=AuthenticatedRaiseMatcher(expected=_Expected("TypeError")),
                unmet=ExpectationNotMetEffect("raise", "assertion-site"),
            ),
        )


def test_same_named_exception_keeps_distinct_operation_origins():
    source = _site()
    exception_type = _Expected("TypeError").identity
    origin = source_coordinate(source)
    first = NativeOperationResolutionV1.exceptional(
        exception_type_coordinate=exception_type,
        operation_occurrence=origin,
    )
    second = NativeOperationResolutionV1.exceptional(
        exception_type_coordinate=exception_type,
        operation_occurrence=type(origin)(
            origin.source_cid,
            origin.start_line + 1,
            origin.start_col,
            origin.end_line + 1,
            origin.end_col,
        ),
    )

    first_exit = first.project(source_node=source).exits[0]
    second_exit = second.project(source_node=source).exits[0]
    assert isinstance(first_exit, Halted)
    assert isinstance(second_exit, Halted)
    assert first_exit.effect.exception_type_coordinate == exception_type
    assert second_exit.effect.exception_type_coordinate == exception_type
    assert first_exit.effect.occurrence != second_exit.effect.occurrence


def _setitem_site():
    source = "def store(receiver, index, value):\n    receiver[index] = value\n"
    tree = SourceFile(
        (source, "setitem_operation.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(tree.functions()).fragment


def _setattr_site():
    source = "def store(receiver, value):\n    receiver.name = value\n"
    tree = SourceFile(
        (source, "setattr_operation.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(tree.functions()).fragment


def _setitem_carrier():
    """Mint setitem in discharge order: receiver, index, value."""
    receiver = _coordinate("receiver", 0)
    index = _coordinate("index", 1)
    value = _coordinate("value", 2)
    carrier = NativeOperationExitCarrierV1.mint(
        site=_setitem_site(),
        operator="setitem",
        operands=(
            SymbolicValue(make_var("receiver"), receiver),
            SymbolicValue(make_var("index"), index),
            SymbolicValue(make_var("value"), value),
        ),
        coordinates=(receiver, index, value),
    )
    return carrier, receiver, index, value


@dataclass(frozen=True)
class _AttrStoreReceiver(FloorValue):
    """Minimal Floor receiver that owns ``setattr`` for discharge twins.

    Window 17534 owns production Floor ``setattr`` arms; this test double only
    authenticates the projector table's ``setattr_named`` unwrap path.
    """

    fields: tuple[tuple[str, FloorValue], ...] = ()

    def setattr(self, name, value, site):
        del site
        remaining = tuple(field for field in self.fields if field[0] != name)
        return Complete(_AttrStoreReceiver((*remaining, (name, value))))

    def to_term(self, *, owner: str):
        del owner
        return ctor(
            "test:attr_store_receiver",
            [
                ctor(
                    "test:attr_store_field",
                    [str_const(name), field.to_term(owner="attr-store")],
                )
                for name, field in self.fields
            ],
        )


def test_setitem_discharges_in_receiver_index_value_order_and_completes():
    """``receiver[index] = value`` discharge order is receiver, index, value."""
    carrier, receiver, index, value = _setitem_carrier()

    exits = carrier.discharge(
        {
            receiver.coordinate_cid: ListValue((TermValue(0), TermValue(1))),
            index.coordinate_cid: TermValue(0),
            value.coordinate_cid: TermValue(9),
        }
    )

    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    assert completed.value == ListValue((TermValue(9), TermValue(1)))


def test_setitem_discharges_and_halts_with_named_exception_identity():
    """Store halt identity comes from the operation floor, never the boundary."""
    carrier, receiver, index, value = _setitem_carrier()

    exits = carrier.discharge(
        {
            receiver.coordinate_cid: ListValue((TermValue(0),)),
            index.coordinate_cid: TermValue(4),
            value.coordinate_cid: TermValue(9),
        }
    )

    assert len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _Expected("IndexError").identity
    assert halted.effect.occurrence is not None


def test_setattr_named_unwraps_string_value_and_discharges():
    """Window 17534: name is StringValue; projector unwraps with ``name.value``."""
    receiver = _coordinate("receiver", 0)
    value = _coordinate("value", 1)
    carrier = NativeOperationExitCarrierV1.mint(
        site=_setattr_site(),
        operator="setattr_named",
        operands=(
            SymbolicValue(make_var("receiver"), receiver),
            StringValue("name"),
            SymbolicValue(make_var("value"), value),
        ),
        coordinates=(receiver, None, value),
    )

    exits = carrier.discharge(
        {
            receiver.coordinate_cid: _AttrStoreReceiver(),
            value.coordinate_cid: TermValue(7),
        }
    )

    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    assert completed.value == _AttrStoreReceiver((("name", TermValue(7)),))


def test_source_evaluation_order_rhs_receiver_index_is_independent_of_discharge():
    """Python eval order (RHS, receiver, index) is not the setitem call order.

    Source producers evaluate value first, then the target's receiver, then
    the index.  Discharge still binds ``receiver, index, value`` because the
    Floor method is ``setitem(index, value)``.  Conflating the two orders is
    the defect the explicit projector table exists to prevent.
    """
    order: list[str] = []

    @dataclass(frozen=True)
    class _Probe(Sugar):
        label: str
        payload: FloorValue

        def desugar(self, ctx=None):
            del ctx
            order.append(self.label)
            return Complete(self.payload)

        @classmethod
        def witnesses(cls):
            return ()

    # The store producer's source chain (window 10876): value → receiver → index.
    value = _Probe("value", TermValue(9))
    receiver = _Probe("receiver", ListValue((TermValue(0),)))
    index = _Probe("index", TermValue(0))
    source_outcome = value.desugar().and_then(
        lambda stored: receiver.desugar().and_then(
            lambda recv: index.desugar().and_then(
                lambda idx: recv.setitem(idx, stored, _setitem_site())
            )
        )
    )
    assert order == ["value", "receiver", "index"]
    assert isinstance(source_outcome, Complete)
    assert source_outcome.value == ListValue((TermValue(9),))

    # Discharge order is independently receiver, index, value on the table.
    import inspect

    parameters = tuple(
        inspect.signature(_NATIVE_OPERATION_PROJECTORS["setitem"]).parameters
    )
    assert parameters == ("receiver", "index", "value", "site")
    assert parameters[:3] != ("value", "receiver", "index")


def test_lying_swapped_index_and_value_must_fail_to_match_correct_store():
    """Swapped index/value still calls cleanly — so order must be enforced by twins.

    A generic splat would hide this: both orders invoke ``setitem`` without
    TypeError.  The explicit projector names the signature so a producer that
    mints value before index cannot silently claim the truthful store face.
    """
    receiver = _coordinate("receiver", 0)
    index = _coordinate("index", 1)
    value = _coordinate("value", 2)
    site = _setitem_site()
    truthful = NativeOperationExitCarrierV1.mint(
        site=site,
        operator="setitem",
        operands=(
            SymbolicValue(make_var("receiver"), receiver),
            SymbolicValue(make_var("index"), index),
            SymbolicValue(make_var("value"), value),
        ),
        coordinates=(receiver, index, value),
    )
    # LYING mint: index and value slots swapped relative to the projector.
    lying = NativeOperationExitCarrierV1.mint(
        site=site,
        operator="setitem",
        operands=(
            SymbolicValue(make_var("receiver"), receiver),
            SymbolicValue(make_var("value"), value),
            SymbolicValue(make_var("index"), index),
        ),
        coordinates=(receiver, value, index),
    )

    actuals = {
        receiver.coordinate_cid: ListValue((TermValue(0), TermValue(1), TermValue(2))),
        index.coordinate_cid: TermValue(1),
        value.coordinate_cid: TermValue(99),
    }
    truthful_exits = truthful.discharge(actuals)
    lying_exits = lying.discharge(actuals)

    assert isinstance(truthful_exits.exits[0], Completed)
    assert truthful_exits.exits[0].value == ListValue(
        (TermValue(0), TermValue(99), TermValue(2))
    )
    # The lying order stores at index 99 (the value) — IndexError — or at the
    # wrong cell.  Either way it must not equal the truthful post-state.
    lying_face = lying_exits.exits[0]
    if isinstance(lying_face, Completed):
        assert lying_face.value != truthful_exits.exits[0].value
    else:
        assert isinstance(lying_face, Halted)


def test_lying_operator_absent_from_projector_table_is_undischarged_not_panic():
    """An operator not in the table is undischarged — never panic, never complete."""
    carrier, left, right = _carrier(operator="invented_store_protocol")

    with pytest.raises(SugarNotWritten, match="projector unavailable"):
        carrier.discharge(
            {left.coordinate_cid: TermValue(1), right.coordinate_cid: TermValue(2)}
        )


def test_mismatched_operand_coordinate_lengths_still_construction_panic():
    """Internal length disagreement remains a loud panic, not undischarged.

    #6613 owns this invariant at ``__post_init__``: replace constructs a new
    carrier and panics before discharge can run.  Missing authenticated
    evidence is a different axis and stays undischarged.
    """
    carrier, left, _right = _carrier()
    with pytest.raises(ConstructionPanic, match="one authenticated coordinate slot"):
        replace(carrier, coordinates=(left,))


def test_production_minted_operators_equal_projector_table_exactly():
    """Every production-minted operator has exactly one projector, and vice versa.

    This is the durable fix for the integration-loss class where a producer
    mints ``operator="subscript"`` (or any new name) while discharge has no
    projector: the mint site stays green, the acceptance grep stays green, and
    discharge silently undischarges.  Both directions must go red on drift.
    """
    production = production_native_operation_operators()
    projectors = frozenset(_NATIVE_OPERATION_PROJECTORS)
    missing_projectors = production - projectors
    orphan_projectors = projectors - production
    assert missing_projectors == frozenset(), (
        "production mints operators with no projector: "
        f"{sorted(missing_projectors)}"
    )
    assert orphan_projectors == frozenset(), (
        "projectors with no production mint path: "
        f"{sorted(orphan_projectors)}"
    )
    assert "subscript" in projectors
    assert "setitem" in projectors
    assert "setattr_named" in projectors


def test_symbolic_formal_subscript_discharges_completed_through_projector():
    """Integration tooth: SymbolicValue.subscript → mint → table → Completed.

    A unit poke of the table would pass while ``subscript`` was missing from
    it.  This path starts at the #6611 producer, mints the carrier, and
    discharges through the projector to a completed list element.
    """
    receiver_coordinate = _coordinate("receiver", 0)
    formal = SymbolicValue(make_var("receiver"), receiver_coordinate)
    index = TermValue(0)
    site = _site()

    outcome = formal.subscript(index, site)
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.demand.operator == "subscript"
    assert outcome.demand.operand_coordinate_cids == (
        receiver_coordinate.coordinate_cid,
        None,
    )

    exits = outcome.discharge(
        {
            receiver_coordinate.coordinate_cid: ListValue(
                (TermValue(7), TermValue(8))
            ),
        }
    )
    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    assert completed.value == TermValue(7)


def test_symbolic_formal_subscript_discharges_authenticated_exceptional_through_projector():
    """Integration tooth: SymbolicValue.subscript → mint → table → named halt.

    ``None[0]`` is TypeError with an authenticated exception-type coordinate.
    The projector must route the Floor face; a missing projector would undischarge
    with ``projector unavailable`` instead.
    """
    receiver_coordinate = _coordinate("receiver", 0)
    formal = SymbolicValue(make_var("receiver"), receiver_coordinate)
    outcome = formal.subscript(TermValue(0), _site())
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.demand.operator == "subscript"

    exits = outcome.discharge(
        {receiver_coordinate.coordinate_cid: NoneValue()}
    )
    assert len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _Expected("TypeError").identity
    assert halted.effect.occurrence is not None
