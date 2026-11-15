"""Slice-subscript store: ``obj[lo:hi] = value`` / ``obj[:] = value``.

Same setitem door as scalar index store (#setitem formal), with SliceValue as
the index species:

  - SliceSugar builds Floor ``SliceValue`` (not a SymbolicValue term shell)
  - ListValue.setitem handles ground SliceValue (Python list slice assignment)
  - Helper alone stays undischarged setitem when formals own receiver/value
  - Production callers (positional / keyword / default) bind through the real
    call binder; the list reaches ``helper`` by binding, so its contents are
    not current there (``object_identity.contents_current``) and the store is
    the cited undecided ``list.__setitem__`` -- never a post-state read off
    the contents the list arrived with
  - Wrong-coordinate / missing actual refuse fabricated completion
  - Extended-slice length mismatch is named ValueError; non-sequence RHS TypeError

Literal / ground bounds are the vertical; formal bounds nested inside a slice
remain a separate open (coordinates do not yet expand into the setitem demand).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    BytesValue,
    DictValue,
    ListValue,
    SetValue,
    SliceValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.sugar.slice_sugar import SliceSugar
from sugar_lift_py_tests.sugar.store_effect_sugar import SubscriptStoreEffectSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str = "slice_store.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper(source: str):
    tree = _tree(source, "helper.py")
    function = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    return function, function.sugar().desugar(None)


def _call_outcome(signature: str, body: str, actuals: str):
    source = f"def helper({signature}):\n    {body}\n\nhelper({actuals})\n"
    tree = _tree(source, "slice_call.py")
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def _undecided_store(outcome, method: str = "__setitem__") -> None:
    """A caller's store through ``helper``'s formal ``obj``.

    The list reaches ``helper`` by binding (``object_identity.arrived``), so
    its contents are not current there and the container law does not read
    them (``builtin_container_method.apply``).  The store is the cited
    undecided ``list.<method>`` (``builtin_container_call_sugar._opaque_pair``):
    it completes under ``python:builtin_method.completes`` and halts with an
    ``UndeterminedRaiseEffect`` under the complement -- never one completion
    whose post-state is read off the contents the list arrived with."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Halted

    assert isinstance(outcome, ExitSet), type(outcome)
    assert outcome.completed_value() is None, outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    halted = [face for face in outcome.exits if isinstance(face, Halted)]
    assert len(completed) == 1 and len(halted) == 1, outcome
    assert len(outcome.exits) == 2, outcome
    guard = completed[0].guard
    assert getattr(guard, "name", None) == "python:builtin_method.completes", guard
    assert f"list.{method}" in repr(guard), guard
    effect = halted[0].effect
    assert isinstance(effect, UndeterminedRaiseEffect), effect
    assert effect.exception_name is None, effect
    assert effect.producer_node_owner == f"BuiltinMethodCall:list.{method}", effect


@dataclass(frozen=True)
class _FloorSugar(Sugar):
    value: object

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(self.value)

    @classmethod
    def witnesses(cls):
        return ()


def _site():
    tree = _tree("def f(obj, value):\n    obj[1:3] = value\n")
    function = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    return function.body[0].fragment


# ---------------------------------------------------------------------------
# SliceSugar → SliceValue
# ---------------------------------------------------------------------------


def test_slice_sugar_builds_floor_slice_value() -> None:
    from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar

    site = _site()
    out = SliceSugar(
        IntLiteralSugar(1, site=site),
        IntLiteralSugar(3, site=site),
        None,
        site,
    ).desugar(None)
    value = out.completed_value()
    assert isinstance(value, SliceValue)
    assert value.lower == TermValue(1)
    assert value.upper == TermValue(3)
    assert value.step is None


def test_slice_sugar_omitted_bounds_are_none() -> None:
    site = _site()
    out = SliceSugar(None, None, None, site).desugar(None)
    assert out.completed_value() == SliceValue(None, None, None)


def test_slice_lower_halt_skips_upper_and_step_desugar() -> None:
    """Lower-bound halt must not evaluate upper/step (LTR bound law)."""
    from dataclasses import field as dataclass_field

    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar

    site = _site()
    log: list[str] = []

    @dataclass(frozen=True)
    class _HaltBound(ConstructedTermSugar):
        label: str
        site: object = dataclass_field(compare=False)

        def to_term(self, *, owner: str):
            del owner
            return ctor("halt-bound", [str_const(self.label)])

        def desugar(self, ctx=None):
            del ctx
            log.append(self.label)
            return ExitSet.halted(
                RaiseEffect(
                    exception_name="ValueError",
                    blame=str(self.site),
                    occurrence=str(self.site),
                    producer_node_owner=f"halt:{self.label}",
                )
            )

        @classmethod
        def witnesses(cls):
            return ()

    @dataclass(frozen=True)
    class _LogBound(ConstructedTermSugar):
        label: str
        site: object = dataclass_field(compare=False)

        def to_term(self, *, owner: str):
            del owner
            return ctor("log-bound", [str_const(self.label)])

        def desugar(self, ctx=None):
            del ctx
            log.append(self.label)
            return ExitSet.completed(TermValue(0))

        @classmethod
        def witnesses(cls):
            return ()

    out = SliceSugar(
        _HaltBound("lower", site),
        _LogBound("upper", site),
        _LogBound("step", site),
        site,
    ).desugar(None)
    assert out.exits and out.halts() == out.exits
    assert log == ["lower"]
    with pytest.raises(AssertionError):
        assert "upper" in log


# ---------------------------------------------------------------------------
# ListValue.setitem ground slice assignment
# ---------------------------------------------------------------------------


def test_list_slice_assignment_replaces_range() -> None:
    site = _site()
    receiver = fresh(
        ListValue, (TermValue(0), TermValue(1), TermValue(2), TermValue(3))
    )
    index = SliceValue(TermValue(1), TermValue(3), None)
    rhs = fresh(ListValue, (TermValue(9), TermValue(9)))
    out = receiver.setitem(index, rhs, site, None)
    assert out.completed_value() == fresh(
        ListValue, (TermValue(0), TermValue(9), TermValue(9), TermValue(3))
    )


def test_list_slice_assignment_can_change_length() -> None:
    site = _site()
    receiver = fresh(
        ListValue, (TermValue(0), TermValue(1), TermValue(2), TermValue(3))
    )
    index = SliceValue(TermValue(1), TermValue(3), None)
    out = receiver.setitem(index, fresh(ListValue, (TermValue(8),)), site, None)
    assert out.completed_value() == fresh(ListValue, (TermValue(0), TermValue(8), TermValue(3)))


def test_list_full_slice_replaces_all() -> None:
    site = _site()
    receiver = fresh(ListValue, (TermValue(0), TermValue(1)))
    out = receiver.setitem(
        SliceValue(None, None, None),
        fresh(ListValue, (TermValue(7), TermValue(8))),
        site,
        None,
    )
    assert out.completed_value() == fresh(ListValue, (TermValue(7), TermValue(8)))


def test_discrimination_slice_store_is_not_scalar_index_overwrite() -> None:
    site = _site()
    receiver = fresh(
        ListValue, (TermValue(0), TermValue(1), TermValue(2), TermValue(3))
    )
    out = receiver.setitem(
        SliceValue(TermValue(1), TermValue(3), None),
        fresh(ListValue, (TermValue(9), TermValue(9))),
        site,
        None,
    )
    assert out.completed_value().elements[1] == TermValue(9)
    with pytest.raises(AssertionError):
        # Lying: scalar setitem at 1 would leave index 2 as TermValue(2).
        assert out.completed_value() == fresh(
            ListValue, (TermValue(0), TermValue(9), TermValue(2), TermValue(3))
        )


def test_extended_slice_length_mismatch_is_value_error() -> None:
    from sugar_lift_py_tests.effect import RaiseEffect

    site = _site()
    receiver = fresh(
        ListValue, (TermValue(0), TermValue(1), TermValue(2), TermValue(3))
    )
    # ::2 selects two positions; one RHS element → ValueError.
    out = receiver.setitem(
        SliceValue(None, None, TermValue(2)),
        fresh(ListValue, (TermValue(1),)),
        site,
        None,
    )
    # Floor ground exit is a halt: ExitSet.halted(effect).
    assert out.halts() == out.exits
    (halt,) = out.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "ValueError"


def test_non_sequence_rhs_is_type_error() -> None:
    from sugar_lift_py_tests.effect import RaiseEffect

    site = _site()
    receiver = fresh(ListValue, (TermValue(0), TermValue(1), TermValue(2)))
    out = receiver.setitem(
        SliceValue(TermValue(0), TermValue(2), None),
        TermValue(9),
        site,
        None,
    )
    assert out.halts() == out.exits
    (halt,) = out.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "TypeError"


def test_tuple_rhs_is_accepted_for_slice_store() -> None:
    site = _site()
    receiver = fresh(ListValue, (TermValue(0), TermValue(1), TermValue(2)))
    out = receiver.setitem(
        SliceValue(TermValue(0), TermValue(2), None),
        TupleValue((TermValue(8), TermValue(8))),
        site,
        None,
    )
    assert out.completed_value() == fresh(ListValue, (TermValue(8), TermValue(8), TermValue(2)))


def test_string_rhs_projects_authenticated_characters() -> None:
    site = _site()
    out = fresh(ListValue, (TermValue(0),)).setitem(
        SliceValue(None, None, None), StringValue("ab"), site, None
    )
    assert out == ExitSet.completed(
        fresh(ListValue, (StringValue("a"), StringValue("b")))
    )


def test_string_rhs_is_not_one_unsplit_string_or_typeerror() -> None:
    site = _site()
    out = fresh(ListValue, (TermValue(0),)).setitem(
        SliceValue(None, None, None), StringValue("ab"), site, None
    )
    assert out != ExitSet.completed(fresh(ListValue, (StringValue("ab"),)))
    from sugar_lift_py_tests.effect import RaiseEffect

    assert not (
        out.exits
        and out.halts() == out.exits
        and any(isinstance(halt.effect, RaiseEffect) for halt in out.halts())
    )


def test_bytes_rhs_projects_authenticated_integer_bytes() -> None:
    site = _site()
    out = fresh(ListValue, (TermValue(0),)).setitem(
        SliceValue(None, None, None), BytesValue(b"AB"), site, None
    )
    assert out == ExitSet.completed(fresh(ListValue, (TermValue(65), TermValue(66))))


def test_bytes_rhs_is_not_bytes_singletons_or_typeerror() -> None:
    site = _site()
    out = fresh(ListValue, (TermValue(0),)).setitem(
        SliceValue(None, None, None), BytesValue(b"AB"), site, None
    )
    assert out != ExitSet.completed(
        fresh(ListValue, (BytesValue(b"A"), BytesValue(b"B")))
    )
    from sugar_lift_py_tests.effect import RaiseEffect

    assert not (
        out.exits
        and out.halts() == out.exits
        and any(isinstance(halt.effect, RaiseEffect) for halt in out.halts())
    )


def test_dict_rhs_projects_authenticated_insertion_order_keys() -> None:
    site = _site()
    rhs = fresh(
        DictValue,
        ((StringValue("a"), TermValue(1)), (StringValue("b"), TermValue(2))),
    )
    out = fresh(ListValue, (TermValue(0),)).setitem(
        SliceValue(None, None, None), rhs, site, None
    )
    assert out == ExitSet.completed(
        fresh(ListValue, (StringValue("a"), StringValue("b")))
    )


def test_dict_rhs_is_not_values_or_typeerror() -> None:
    site = _site()
    rhs = fresh(
        DictValue,
        ((StringValue("a"), TermValue(1)), (StringValue("b"), TermValue(2))),
    )
    out = fresh(ListValue, (TermValue(0),)).setitem(
        SliceValue(None, None, None), rhs, site, None
    )
    assert out != ExitSet.completed(fresh(ListValue, (TermValue(1), TermValue(2))))
    from sugar_lift_py_tests.effect import RaiseEffect

    assert not (
        out.exits
        and out.halts() == out.exits
        and any(isinstance(halt.effect, RaiseEffect) for halt in out.halts())
    )


def test_set_rhs_keeps_unowned_runtime_iteration_order_loud() -> None:
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    site = _site()
    with pytest.raises(ConstructionPanic) as raised:
        fresh(ListValue, (TermValue(0),)).setitem(
            SliceValue(None, None, None),
            fresh(
                SetValue,
                (StringValue("constructed-first"), StringValue("constructed-second")),
            ),
            site,
            None,
        )
    assert raised.value.info.owner == "SetValue.slice_assign_iterable_with"
    assert "iteration order" in raised.value.info.observed
    assert "producer-owned" in raised.value.info.fix


def test_set_rhs_does_not_fabricate_construction_order_or_typeerror() -> None:
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    site = _site()
    constructed = (StringValue("constructed-first"), StringValue("constructed-second"))
    with pytest.raises(ConstructionPanic):
        fabricated = fresh(ListValue, (TermValue(0),)).setitem(
            SliceValue(None, None, None), fresh(SetValue, constructed), site, None
        )
        assert fabricated == ExitSet.completed(fresh(ListValue, constructed))


# ---------------------------------------------------------------------------
# Production SubscriptStoreEffectSugar + SliceSugar path
# ---------------------------------------------------------------------------


def test_production_store_sugar_with_slice_index_completes() -> None:
    from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar

    site = _site()
    log: list[str] = []

    @dataclass(frozen=True)
    class _Obs(Sugar):
        label: str
        value: object

        def desugar(self, ctx=None):
            del ctx
            log.append(self.label)
            return ExitSet.completed(self.value)

        @classmethod
        def witnesses(cls):
            return ()

    sugar = SubscriptStoreEffectSugar(
        receiver=_Obs(
            "receiver", fresh(ListValue, (TermValue(0), TermValue(1), TermValue(2)))
        ),
        index=SliceSugar(
            IntLiteralSugar(0, site=site),
            IntLiteralSugar(2, site=site),
            None,
            site,
        ),
        value=_Obs("value", fresh(ListValue, (TermValue(9),))),
        site=site,
    )
    out = sugar.desugar(None)
    # Python order: RHS, receiver, index (slice bounds inside index).
    assert log[0] == "value"
    assert log[1] == "receiver"
    assert out.completed_value() == fresh(ListValue, (TermValue(9), TermValue(2)))


# ---------------------------------------------------------------------------
# Formal helper alone + production callers
# ---------------------------------------------------------------------------


def test_helper_alone_slice_store_is_undischarged_setitem() -> None:
    """Literal slice bounds; formal receiver and value — setitem demand."""
    _, pending = _helper("def helper(obj, value):\n    obj[1:3] = value\n")
    assert isinstance(pending, NativeOperationExitCarrierV1), type(pending)
    assert pending.demand.operator == "setitem"
    # Index is the ground SliceValue — no formal coordinate on the slice itself.
    assert pending.demand.operand_coordinate_cids[1] is None
    assert pending.demand.operand_coordinate_cids[0] is not None
    assert pending.demand.operand_coordinate_cids[2] is not None
    _unanswered(pending, {})


def _unanswered(pending, actuals) -> None:
    """An absent actual leaves the store the cited unanswered face (#7825):
    owed as an ``undecided`` member, never an unconditional completion."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    exits = pending.discharge(None, actuals)
    assert pending.unanswered_call() in owed_calls(exits)
    assert exits.completed_value() is None


def test_discrimination_helper_alone_is_not_completed() -> None:
    _, pending = _helper("def helper(obj, value):\n    obj[1:3] = value\n")
    with pytest.raises(AssertionError):
        assert isinstance(pending, ExitSet) and pending.completed_value() is not None


def test_positional_caller_slice_store_is_the_undecided_store() -> None:
    outcome = _call_outcome(
        "obj, value",
        "obj[1:3] = value",
        "[0, 1, 2, 3], [9, 9]",
    )
    _undecided_store(outcome)


def test_keyword_caller_slice_store_is_the_undecided_store() -> None:
    outcome = _call_outcome(
        "obj, value",
        "obj[1:3] = value",
        "obj=[0, 1, 2, 3], value=[8]",
    )
    _undecided_store(outcome)


def test_default_caller_slice_store_is_the_undecided_store() -> None:
    outcome = _call_outcome(
        "obj, value=[7, 7]",
        "obj[1:3] = value",
        "[0, 1, 2, 3]",
    )
    _undecided_store(outcome)


def test_full_slice_caller_store_is_the_undecided_store() -> None:
    outcome = _call_outcome(
        "obj, value",
        "obj[:] = value",
        "[0, 1], [5, 6, 7]",
    )
    _undecided_store(outcome)


def test_discrimination_caller_store_never_reads_the_arrived_contents() -> None:
    """Neither the pre-store contents nor the post-state Python computes from
    them is presented: the arrived list's contents are not read."""
    outcome = _call_outcome(
        "obj, value",
        "obj[1:3] = value",
        "[0, 1, 2, 3], [9, 9]",
    )
    _undecided_store(outcome)
    computed = (TermValue(0), TermValue(9), TermValue(9), TermValue(3))
    assert f"elements={computed!r}" not in repr(outcome)


# ---------------------------------------------------------------------------
# Wrong-coordinate / missing actual
# ---------------------------------------------------------------------------


def test_wrong_coordinate_cannot_discharge_slice_store() -> None:
    function, pending = _helper("def helper(obj, value):\n    obj[1:3] = value\n")
    assert isinstance(pending, NativeOperationExitCarrierV1)
    coords = function.formal_coordinates()
    obj_c, value_c = coords[0], coords[1]
    _unanswered(
        pending,
        {
            f"wrong:{obj_c.coordinate_cid}": fresh(ListValue, (TermValue(0),)),
            value_c.coordinate_cid: fresh(ListValue, (TermValue(1),)),
        },
    )


def test_missing_actual_does_not_fabricate_completed_slice_store() -> None:
    _, pending = _helper("def helper(obj, value):\n    obj[1:3] = value\n")
    _unanswered(pending, {})


# ---------------------------------------------------------------------------
# Production teeth: delete-slice, step-zero, occurrence, formal-bound gap
# ---------------------------------------------------------------------------


def test_production_delete_slice_caller_is_the_undecided_delete() -> None:
    """``del obj[1:3]`` through production call binder, on a list that
    arrived by binding."""
    outcome = _call_outcome(
        "obj",
        "del obj[1:3]",
        "[0, 1, 2, 3]",
    )
    _undecided_store(outcome, "__delitem__")


def test_step_zero_setitem_is_named_valueerror_with_occurrence() -> None:
    from sugar_lift_py_tests.effect import RaiseEffect

    site = _site()
    out = fresh(ListValue, (TermValue(0), TermValue(1))).setitem(
        SliceValue(None, None, TermValue(0)),
        fresh(ListValue, ()),
        site,
        None,
    )
    assert out.halts() == out.exits
    (halt,) = out.halts()
    assert isinstance(halt.effect, RaiseEffect)
    effect = halt.effect
    assert effect.exception_name == "ValueError"
    assert effect.producer_node_owner == "ListValue.setitem"
    assert effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


def test_step_zero_delitem_is_named_valueerror_with_occurrence() -> None:
    from sugar_lift_py_tests.effect import RaiseEffect

    site = _site()
    out = fresh(ListValue, (TermValue(0), TermValue(1), TermValue(2))).delitem(
        SliceValue(None, None, TermValue(0)),
        site,
        None,
    )
    assert out.halts() == out.exits
    (halt,) = out.halts()
    assert isinstance(halt.effect, RaiseEffect)
    effect = halt.effect
    assert effect.exception_name == "ValueError"
    assert effect.producer_node_owner == "ListValue.delitem"
    assert effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


def test_per_phase_occurrence_identity_setitem_vs_delitem() -> None:
    """Setitem and delitem step-zero exits share type, not occurrence owner."""
    site = _site()
    set_out = fresh(ListValue, (TermValue(0),)).setitem(
        SliceValue(None, None, TermValue(0)), fresh(ListValue, ()), site, None
    )
    del_out = fresh(ListValue, (TermValue(0),)).delitem(
        SliceValue(None, None, TermValue(0)), site, None
    )
    # A step-zero slice is a ground halt: every exit of each is the one halt.
    assert set_out.halts() == set_out.exits
    assert del_out.halts() == del_out.exits
    (set_halt,) = set_out.halts()
    (del_halt,) = del_out.halts()
    set_e = set_halt.effect
    del_e = del_halt.effect
    assert set_e.exception_name == del_e.exception_name == "ValueError"
    assert set_e.producer_node_owner == "ListValue.setitem"
    assert del_e.producer_node_owner == "ListValue.delitem"
    assert set_e.producer_node_owner != del_e.producer_node_owner
    with pytest.raises(AssertionError):
        assert set_e.producer_node_owner == del_e.producer_node_owner


def test_a_formal_slice_bound_defers_the_slice_to_the_caller() -> None:
    """A parameter bound (``obj[lo:3] = value``) defers the slice itself: the
    ``slice`` carrier, the bound's coordinate in its slot (#7757).  The helper
    alone is the cited unanswered face, never a fabricated store."""
    function, pending = _helper("def helper(obj, lo, value):\n    obj[lo:3] = value\n")
    lo = next(
        coordinate
        for coordinate in function.sugar().formal_coordinates
        if coordinate.declared_name == "lo"
    )

    assert isinstance(pending, NativeOperationExitCarrierV1), type(pending)
    assert pending.demand.operator == "slice"
    assert pending.demand.operand_coordinate_cids == (lo.coordinate_cid, None, None)
    _unanswered(pending, {})


def test_a_caller_store_through_a_formal_slice_bound_is_the_undecided_store() -> None:
    """The bound ``lo`` arrives as the immutable ``1`` and builds the slice;
    the store is then on a list that arrived by binding."""
    outcome = _call_outcome(
        "obj, lo, value",
        "obj[lo:3] = value",
        "[0, 1, 2, 3], 1, [9]",
    )
    _undecided_store(outcome)


def test_slice_assign_iterable_door_not_getattr_probe() -> None:
    """RHS routes through SliceAssignIterableOperation — no species ladder."""
    import inspect

    from sugar_lift_py_tests.floor.floor_value import FloorValue
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.operations.slice_assign_iterable_operation import (
        SliceAssignIterableOperation,
    )
    site = _site()
    # Exact list answers members.
    exact = SliceAssignIterableOperation(owner="test", blame=site).submit(
        fresh(ListValue, (TermValue(1), TermValue(2))), None
    )
    assert exact.completed_value() == (TermValue(1), TermValue(2))
    # Undecided stays a halt (not construction panic, not getattr).
    undecided = SliceAssignIterableOperation(owner="test", blame=site).submit(
        SymbolicValue(make_var("xs")), None
    )
    assert undecided.exits and undecided.halts() == undecided.exits
    assert "getattr(" not in inspect.getsource(FloorValue.slice_assign_iterable_with)
