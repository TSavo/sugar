from __future__ import annotations

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    NativeOperationResolutionV1,
    authenticated_exceptional_resolution_count,
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
from sugar_lift_py_tests.floor import NoneValue, SymbolicValue, TermValue
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, make_var, str_const
from sugar_lift_py_tests.outcome import (
    Completed,
    ExitSet,
    Halted,
    outcome_to_exitset,
    true_guard,
)
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


def test_missing_authenticated_actual_remains_typed_loud():
    carrier, left, _ = _carrier()

    with pytest.raises(ConstructionPanic, match="authenticated actual"):
        carrier.discharge({left.coordinate_cid: TermValue(1)})


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
    carrier, left, right = _carrier("is_identical")

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
