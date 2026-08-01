"""Vertical completion: formal ``setitem`` through the n-ary projector.

Python semantic law made constructible:

  For ``helper(obj, key, value)`` whose body is ``obj[key] = value``, the store
  dispatches ``__setitem__`` — a different method and obligation from the load
  path.  Helper alone stays undischarged.  An ordinary source caller
  (positional, keyword, or default) supplies authenticated actuals; discharge
  projects Completed field stores or named exceptional faces whose origin is
  Floor ``setitem``, never an enclosing boundary type.

Mint contract (matches #6614 projector):

  operator ``setitem``
  operands ``(receiver, index, value)``  — discharge order
  coordinates ``(receiver.formal?, index.formal?, value.formal?)``
  projector: ``receiver.setitem(index, value, site)``

Source evaluation order is independent of discharge order:

  Python evaluates RHS, then receiver, then index.
  Discharge binds receiver, index, value.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import ListValue, TermValue, TupleValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.store_effect_sugar import SubscriptStoreEffectSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str = "setitem_caller.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper_definition():
    source = "def helper(obj, key, value):\n    obj[key] = value\n"
    tree = _tree(source, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _call_outcome(signature: str, actuals: str):
    source = (
        f"def helper({signature}):\n" "    obj[key] = value\n\n" f"helper({actuals})\n"
    )
    tree = _tree(source)
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def _assert_named_halt(outcome) -> Halted:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity('TypeError')
    assert isinstance(halted.effect.occurrence_id, str) and ":" in halted.effect.occurrence_id, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    return halted


def _stored_list(completed_face) -> ListValue:
    """Pull the store post-state list out of a function-universe completion."""
    assert isinstance(completed_face, Completed)
    record = getattr(completed_face.value, "record", None)
    assert record is not None
    lists = [s for s in record.statements if isinstance(s, ListValue)]
    assert len(lists) == 1, lists
    return lists[0]


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


# ---------------------------------------------------------------------------
# Helper alone → Undischarged
# ---------------------------------------------------------------------------


def test_helper_alone_is_undischarged_setitem_carrier() -> None:
    _, pending = _helper_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setitem"
    assert len(pending.operands) == 3
    assert len(pending.demand.operand_coordinate_cids) == 3
    # All three formals are present and pairwise distinct.
    cids = pending.demand.operand_coordinate_cids
    assert all(cid is not None for cid in cids)
    assert len(set(cids)) == 3
    # Operand names track discharge order: receiver, index, value.
    assert tuple(value.term.name for value in pending.operands) == (
        "obj",
        "key",
        "value",
    )


def test_missing_caller_actual_is_undischarged_not_completed() -> None:
    """Missing authenticated actuals remain undischarged — never fabricate green."""
    _, pending = _helper_definition()
    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge({})


def test_partial_caller_actual_is_undischarged_discrimination() -> None:
    """Positive twin supplies all three; discrimination omits value and stays red."""
    _, pending = _helper_definition()
    obj_cid, key_cid, value_cid = pending.demand.operand_coordinate_cids
    completed = pending.discharge(
        {
            obj_cid: ListValue((TermValue(0),)),
            key_cid: TermValue(0),
            value_cid: TermValue(9),
        }
    )
    assert isinstance(completed.exits[0], Completed)

    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge(
            {
                obj_cid: ListValue((TermValue(0),)),
                key_cid: TermValue(0),
                # value_cid deliberately omitted
            }
        )


# ---------------------------------------------------------------------------
# Mint contract: discharge order (receiver, index, value)
# ---------------------------------------------------------------------------


def test_setitem_mint_operand_order_matches_projector() -> None:
    """#6613: lengths and order are load-bearing — pin discharge order."""
    _, pending = _helper_definition()
    assert pending.demand.operator == "setitem"
    import inspect

    parameters = tuple(
        inspect.signature(_NATIVE_OPERATION_PROJECTORS["setitem"]).parameters
    )
    assert parameters == ("receiver", "index", "value", "site")
    assert tuple(value.term.name for value in pending.operands) == (
        "obj",
        "key",
        "value",
    )


def test_mint_setitem_carrier_producer_contract() -> None:
    """Producer static method is the one door for formal setitem mint."""
    function, _pending = _helper_definition()
    site = function.body[0].fragment
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.ir import PrimitiveSort

    src = site.source_cid
    owner_def = SourceFragmentCoordinateV1(src, 1, 0, 1, 10)

    def _coord(name: str, ordinal: int):
        return FormalParameterCoordinateV1.mint(
            owner_source_identity_cid=src,
            owner_definition_locus=owner_def,
            declaration_locus=SourceFragmentCoordinateV1(
                src, 1, 10 + ordinal, 1, 12 + ordinal
            ),
            ordinal=ordinal,
            parameter_kind="positional-or-keyword",
            declared_name=name,
            sort=PrimitiveSort("Value"),
        )

    receiver_c = _coord("obj", 0)
    index_c = _coord("key", 1)
    value_c = _coord("value", 2)
    carrier = SubscriptStoreEffectSugar.mint_setitem_carrier(
        site=site,
        receiver=SymbolicValue(make_var("obj"), receiver_c),
        index=SymbolicValue(make_var("key"), index_c),
        value=SymbolicValue(make_var("value"), value_c),
    )
    assert isinstance(carrier, NativeOperationExitCarrierV1)
    assert carrier.demand.operator == "setitem"
    assert carrier.demand.operand_coordinate_cids == (
        receiver_c.coordinate_cid,
        index_c.coordinate_cid,
        value_c.coordinate_cid,
    )


def test_mint_setitem_carrier_rejects_no_formal_coordinate() -> None:
    """Discrimination: ground-only operands cannot use the formal mint door."""
    function, _ = _helper_definition()
    site = function.body[0].fragment
    with pytest.raises(ValueError, match="at least one formal_coordinate"):
        SubscriptStoreEffectSugar.mint_setitem_carrier(
            site=site,
            receiver=ListValue((TermValue(0),)),
            index=TermValue(0),
            value=TermValue(9),
        )


# ---------------------------------------------------------------------------
# Mutable receiver → Completed (positive + discrimination)
# ---------------------------------------------------------------------------


def test_mutable_receiver_completes_store_via_setitem() -> None:
    _, pending = _helper_definition()
    obj_cid, key_cid, value_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            obj_cid: ListValue((TermValue(0), TermValue(1))),
            key_cid: TermValue(0),
            value_cid: TermValue(9),
        }
    )
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    assert _stored_list(exits.exits[0]) == ListValue((TermValue(9), TermValue(1)))


def test_positional_keyword_and_default_callers_complete_same_demand() -> None:
    faces = tuple(
        _call_outcome(sig, actuals).exits[0]
        for sig, actuals in (
            ("obj, key, value", "[0], 0, 9"),
            ("obj, key, value", "obj=[0], key=0, value=9"),
            ("obj, key=0, value=9", "[0]"),
        )
    )
    assert all(isinstance(face, Completed) for face in faces)
    # Same post-state shape across presentation forms.
    assert (
        faces[0].value.arg_values
        == faces[1].value.arg_values
        == faces[2].value.arg_values
    )


def test_discrimination_wrong_cell_is_not_the_completed_store() -> None:
    """Positive stores at key 0; discrimination at key 1 must not match."""
    _, pending = _helper_definition()
    obj_cid, key_cid, value_cid = pending.demand.operand_coordinate_cids
    base = ListValue((TermValue(0), TermValue(1)))
    positive = pending.discharge(
        {obj_cid: base, key_cid: TermValue(0), value_cid: TermValue(9)}
    )
    other = pending.discharge(
        {obj_cid: base, key_cid: TermValue(1), value_cid: TermValue(9)}
    )
    assert isinstance(positive.exits[0], Completed)
    assert isinstance(other.exits[0], Completed)
    pos_list = _stored_list(positive.exits[0])
    other_list = _stored_list(other.exits[0])
    assert pos_list != other_list
    assert pos_list == ListValue((TermValue(9), TermValue(1)))
    assert other_list == ListValue((TermValue(0), TermValue(9)))


# ---------------------------------------------------------------------------
# Invalid index / immutable receiver → named exceptional exit
# ---------------------------------------------------------------------------


def test_invalid_index_halts_with_named_indexerror() -> None:
    _, pending = _helper_definition()
    obj_cid, key_cid, value_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            obj_cid: ListValue((TermValue(0),)),
            key_cid: TermValue(4),
            value_cid: TermValue(9),
        }
    )
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert isinstance(halted.effect.occurrence_id, str) and ":" in halted.effect.occurrence_id, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )


def test_discrimination_valid_index_is_not_indexerror() -> None:
    """Positive twin of IndexError: in-range store completes."""
    _, pending = _helper_definition()
    obj_cid, key_cid, value_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            obj_cid: ListValue((TermValue(0),)),
            key_cid: TermValue(0),
            value_cid: TermValue(9),
        }
    )
    assert isinstance(exits.exits[0], Completed)
    assert not isinstance(exits.exits[0], Halted)


def test_immutable_receiver_halts_with_named_typeerror() -> None:
    # Readable but not settable.
    readable = TupleValue((TermValue(0),)).subscript(TermValue(0), "read.py:1")
    assert readable.value == TermValue(0)

    halted = _assert_named_halt(_call_outcome("obj, key, value", "(0,), 0, 9"))
    assert halted.effect.exception_type_coordinate == _identity("TypeError")
    assert "assertion" not in halted.effect.occurrence


def test_discrimination_list_receiver_is_not_typeerror() -> None:
    """Positive twin of immutable TypeError: list completes."""
    face = _call_outcome("obj, key, value", "[0], 0, 9").exits[0]
    assert isinstance(face, Completed)
    assert not isinstance(face, Halted)


def test_source_caller_indexerror_halts_with_named_identity() -> None:
    halted = _assert_named_halt(_call_outcome("obj, key, value", "[0], 4, 9"))
    assert halted.effect.exception_type_coordinate == _identity("IndexError")


# ---------------------------------------------------------------------------
# Swapped key/value coordinates rejected
# ---------------------------------------------------------------------------


def test_swapped_key_value_coordinates_rejected_against_truthful_store() -> None:
    """Lying mint (index/value swapped) must not equal truthful post-state.

    A generic splat would hide this: both orders invoke ``setitem`` without
    TypeError.  Explicit discharge order makes the lying face distinguishable.
    """
    function, truthful = _helper_definition()
    site = function.body[0].fragment
    from sugar_lift_py_tests.floor import SymbolicValue

    obj_c, key_c, value_c = truthful.coordinates
    # LYING mint: index and value slots swapped relative to the projector.
    lying = NativeOperationExitCarrierV1.mint(
        site=site,
        operator="setitem",
        operands=(
            truthful.operands[0],
            truthful.operands[2],  # value in index slot
            truthful.operands[1],  # index in value slot
        ),
        coordinates=(obj_c, value_c, key_c),
    )

    actuals = {
        obj_c.coordinate_cid: ListValue((TermValue(0), TermValue(1), TermValue(2))),
        key_c.coordinate_cid: TermValue(1),
        value_c.coordinate_cid: TermValue(99),
    }
    truthful_exits = truthful.discharge(actuals)
    lying_exits = lying.discharge(actuals)

    assert isinstance(truthful_exits.exits[0], Completed)
    truthful_list = _stored_list(truthful_exits.exits[0])
    assert truthful_list == ListValue((TermValue(0), TermValue(99), TermValue(2)))
    lying_face = lying_exits.exits[0]
    if isinstance(lying_face, Completed):
        # Lying mint has no function-universe continuation — compare ListValue
        # post-state when completed, else accept a named halt.
        lying_value = lying_face.value
        if isinstance(lying_value, ListValue):
            assert lying_value != truthful_list
        else:
            assert _stored_list(lying_face) != truthful_list
    else:
        assert isinstance(lying_face, Halted)


def test_discrimination_truthful_order_completes_at_correct_cell() -> None:
    """Positive twin of the swapped lying arm."""
    _, truthful = _helper_definition()
    obj_c, key_c, value_c = truthful.coordinates
    exits = truthful.discharge(
        {
            obj_c.coordinate_cid: ListValue((TermValue(0), TermValue(1), TermValue(2))),
            key_c.coordinate_cid: TermValue(1),
            value_c.coordinate_cid: TermValue(99),
        }
    )
    assert isinstance(exits.exits[0], Completed)
    assert _stored_list(exits.exits[0]) == ListValue(
        (TermValue(0), TermValue(99), TermValue(2))
    )


# ---------------------------------------------------------------------------
# Source evaluation order ≠ discharge argument order
# ---------------------------------------------------------------------------


def test_source_evaluation_order_independent_of_discharge_order() -> None:
    """Python eval (value, receiver, index) is not the setitem call order.

    Source producers evaluate value first, then the target's receiver, then
    the index.  Discharge still binds ``receiver, index, value`` because the
    Floor method is ``setitem(index, value)``.
    """
    order: list[str] = []

    @dataclass(frozen=True)
    class _Probe(Sugar):
        label: str
        payload: object

        def desugar(self, ctx=None):
            del ctx
            order.append(self.label)
            return Complete(self.payload)

        @classmethod
        def witnesses(cls):
            return ()

    function, _ = _helper_definition()
    site = function.body[0].fragment
    outcome = SubscriptStoreEffectSugar(
        receiver=_Probe("receiver", ListValue((TermValue(0),))),
        index=_Probe("index", TermValue(0)),
        value=_Probe("value", TermValue(9)),
        site=site,
    ).desugar()

    assert order == ["value", "receiver", "index"]
    assert isinstance(outcome, Complete)
    assert outcome.value == ListValue((TermValue(9),))

    import inspect

    parameters = tuple(
        inspect.signature(_NATIVE_OPERATION_PROJECTORS["setitem"]).parameters
    )
    assert parameters == ("receiver", "index", "value", "site")
    assert parameters[:3] != ("value", "receiver", "index")


def test_discrimination_discharge_order_is_not_source_order() -> None:
    """The projector signature must not collapse to the source eval order."""
    import inspect

    parameters = tuple(
        inspect.signature(_NATIVE_OPERATION_PROJECTORS["setitem"]).parameters
    )
    assert parameters[:3] == ("receiver", "index", "value")
    assert parameters[:3] != ("value", "receiver", "index")


# ---------------------------------------------------------------------------
# Wrong boundary type: exceptional edge remains unconsumed
# ---------------------------------------------------------------------------


def test_wrong_expected_type_leaves_setitem_exception_unconsumed() -> None:
    """Boundary verifies; it cannot create. Wrong T leaves the edge unconsumed."""
    from sugar_lift_py_tests.context_manager_contract import (
        AuthenticatedRaiseMatcher,
        EffectBoundaryDisposition,
    )
    from sugar_lift_py_tests.effect.expectation_not_met_effect import (
        ExpectationNotMetEffect,
    )

    produced = _call_outcome("obj, key, value", "(0,), 0, 9")
    original = produced.exits[0]
    assert isinstance(original, Halted)
    assert original.effect.exception_type_coordinate == _identity("TypeError")

    class _Expected:
        def __init__(self, name: str):
            self.identity = _identity(name)

        def exception_type_identity(self):
            return self.identity

    routed = produced.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected("IndexError")),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )
    remaining = [
        face
        for face in routed.exits
        if isinstance(face, Halted) and face.effect is original.effect
    ]
    assert remaining == [original]
    assert remaining[0].effect.exception_type_coordinate == _identity("TypeError")
