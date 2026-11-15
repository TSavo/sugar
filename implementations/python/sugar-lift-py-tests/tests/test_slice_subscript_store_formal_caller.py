"""Slice-subscript store: ``obj[lo:hi] = value`` / ``obj[:] = value``.

Same setitem door as scalar index store (#setitem formal), with SliceValue as
the index species:

  - SliceSugar builds Floor ``SliceValue`` (not a SymbolicValue term shell)
  - ListValue.setitem handles ground SliceValue (Python list slice assignment)
  - Helper alone stays undischarged setitem when formals own receiver/value
  - Production callers (positional / keyword / default) are the call's
    coordinate and edge, joined at prove (#7757 steps 5 and 6, #8705): the
    edge carries the actuals; the store's post-state is the helper's row
    discharged with them, what prove's one binder binds its carrier with
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
from sugar_source_tree.nodes import FunctionDef
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


def _call_outcome(signature: str, body: str, actuals: dict):
    """The helper's contract row discharged with ``actuals`` (formal name to
    value): what prove's one binder binds its carrier with at a call that
    supplies them.

    A same-file call is its coordinate and edge, joined at prove (#7757
    steps 5 and 6, #8705): the call no longer discharges the helper's store
    carrier, and what the callee leaves of the caller's list is no longer
    carried out of its frame (``caller_visible_values``, deleted by #8739).
    The store's post-state is read off the helper's own row; the call itself
    is the edge (``_the_call``)."""
    function, pending = _helper(f"def helper({signature}):\n    {body}\n")
    assert isinstance(pending, NativeOperationExitCarrierV1), type(pending)
    return pending.discharge(
        None,
        {
            coordinate.coordinate_cid: actuals[coordinate.declared_name]
            for coordinate in function.sugar().formal_coordinates
            if coordinate.declared_name in actuals
        },
    )


def _the_call(signature: str, body: str, actuals: str):
    """``helper({actuals})`` in a caller's body, read off the caller's
    contract row: the call value on its one completed face (the edge, which
    owes its halt under the complement of its ``completes`` atom)."""
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.outcome import Halted
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    source = (
        f"def helper({signature}):\n    {body}\n\n\n"
        f"def caller():\n    return helper({actuals})\n"
    )
    caller = next(
        node
        for node in _tree(source, "slice_call.py").nodes()
        if isinstance(node, FunctionDef) and node.name == "caller"
    )
    outcome = function_universe_outcome(caller)
    assert [face for face in outcome.exits if isinstance(face, Halted)], outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, outcome
    returns = [
        s for s in completed[0].value.record.statements if isinstance(s, ReturnValue)
    ]
    assert returns, completed[0].value
    edge = returns[-1].value
    assert isinstance(edge, CallSiteValue), type(edge)
    return edge


def _coordinate(edge):
    """The call's coordinate ``call:<target>(<arguments>)`` the edge's value
    names: the completed face of the one unanswered call returns
    ``python:call_result(<call term>, <occurrence>)`` (#7757 steps 5 and 6,
    #8705), so the arguments prove's binder binds are the call term's,
    never the result's."""
    result = edge.term
    assert result.name == "python:call_result", result
    call = result.args[0]
    assert call.name.startswith("call:"), call
    return call


def _ints(*values: int) -> ListValue:
    return fresh(ListValue, tuple(TermValue(value) for value in values))


def _stored_list(outcome) -> ListValue:
    """The list after the store, read off the discharged row's record."""
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds

    assert isinstance(outcome, ExitSet), type(outcome)
    assert len(outcome.exits) == 1
    face = outcome.exits[0]
    assert isinstance(face, Completed), type(face)
    binds, value = peel_walrus_binds(face.value)
    left = [bind.assigned_value for bind in binds if bind.name == "actual:0"]
    if left:
        (after,) = left
        assert isinstance(after, ListValue), after
        return after
    force = getattr(value, "force_floor", None)
    if callable(force):
        forced = force(None, owner="slice_store_test")
        from sugar_lift_py_tests.floor.block_value import BlockValue

        if isinstance(forced, BlockValue):
            lists = [s for s in forced.statements if isinstance(s, ListValue)]
            assert lists, forced.statements
            return lists[-1]
        if isinstance(forced, ListValue):
            return forced
    record = getattr(value, "record", None)
    if record is not None:
        lists = [s for s in record.statements if isinstance(s, ListValue)]
        assert lists, record.statements
        return lists[-1]
    raise AssertionError(f"no ListValue post-state: {type(value).__name__}")


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
                RaiseEffect.for_builtin(
                    "ValueError",
                    occurrence=self.site,
                    blame=str(self.site),
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


def test_positional_caller_completes_slice_store() -> None:
    edge = _the_call("obj, value", "obj[1:3] = value", "[0, 1, 2, 3], [9, 9]")
    assert edge.arg_values == (_ints(0, 1, 2, 3), _ints(9, 9))
    outcome = _call_outcome(
        "obj, value",
        "obj[1:3] = value",
        {"obj": _ints(0, 1, 2, 3), "value": _ints(9, 9)},
    )
    stored = _stored_list(outcome)
    assert stored == _ints(0, 9, 9, 3)


def test_keyword_caller_completes_slice_store() -> None:
    from sugar_lift_py_tests.ir import str_const

    edge = _the_call("obj, value", "obj[1:3] = value", "obj=[0, 1, 2, 3], value=[8]")
    arguments = _coordinate(edge).args
    assert [arg.name for arg in arguments] == ["py.kwarg", "py.kwarg"]
    assert [arg.args[0] for arg in arguments] == [
        str_const("obj"),
        str_const("value"),
    ]
    outcome = _call_outcome(
        "obj, value",
        "obj[1:3] = value",
        {"obj": _ints(0, 1, 2, 3), "value": _ints(8)},
    )
    stored = _stored_list(outcome)
    assert stored == _ints(0, 8, 3)


def test_default_caller_completes_slice_store() -> None:
    # The omitted ``value`` binds what the ``def`` statement's module run
    # evaluated, carried on the edge as ``py.default`` (a caller called after
    # import; a module-body call reduced alone is reached by no ``def``
    # statement's run and its default read is refused by name).
    from sugar_lift_py_tests.ir import str_const

    edge = _the_call("obj, value=[7, 7]", "obj[1:3] = value", "[0, 1, 2, 3]")
    assert edge.arg_values == (_ints(0, 1, 2, 3),)
    (default,) = _coordinate(edge).args[1:]
    assert default.name == "py.default"
    assert default.args[0] == str_const("value")
    outcome = _call_outcome(
        "obj, value=[7, 7]",
        "obj[1:3] = value",
        {"obj": _ints(0, 1, 2, 3), "value": _ints(7, 7)},
    )
    stored = _stored_list(outcome)
    assert stored == _ints(0, 7, 7, 3)


def test_full_slice_caller_replaces_entire_list() -> None:
    outcome = _call_outcome(
        "obj, value",
        "obj[:] = value",
        {"obj": _ints(0, 1), "value": _ints(5, 6, 7)},
    )
    stored = _stored_list(outcome)
    assert stored == _ints(5, 6, 7)


def test_discrimination_production_slice_store_is_not_identity() -> None:
    outcome = _call_outcome(
        "obj, value",
        "obj[1:3] = value",
        {"obj": _ints(0, 1, 2, 3), "value": _ints(9, 9)},
    )
    stored = _stored_list(outcome)
    assert stored != _ints(0, 1, 2, 3)


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


def test_production_delete_slice_caller() -> None:
    """``del obj[1:3]`` discharged with the caller's list."""
    outcome = _call_outcome("obj", "del obj[1:3]", {"obj": _ints(0, 1, 2, 3)})
    stored = _stored_list(outcome)
    assert stored == _ints(0, 3)


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


def test_a_caller_completes_a_store_through_a_formal_slice_bound() -> None:
    outcome = _call_outcome(
        "obj, lo, value",
        "obj[lo:3] = value",
        {"obj": _ints(0, 1, 2, 3), "lo": TermValue(1), "value": _ints(9)},
    )
    stored = _stored_list(outcome)
    assert stored == _ints(0, 9, 3)


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
    # Undecided is the one two-faced outcome (not construction panic, not
    # getattr): whether ``xs`` is iterable is not decided at lift, so the
    # store completes only under its own guard and halts with something
    # undetermined under the complement.  Never an unconditional completion.
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect

    undecided = SliceAssignIterableOperation(owner="test", blame=site).submit(
        SymbolicValue(make_var("xs")), None
    )
    assert undecided.completed_value() is None
    (completed,) = [face for face in undecided.exits if isinstance(face, Completed)]
    (halted,) = undecided.halts()
    assert isinstance(halted.effect, UndeterminedRaiseEffect)
    assert halted.guard.kind == "not"
    assert halted.guard.operands == (completed.guard,)
    assert "getattr(" not in inspect.getsource(FloorValue.slice_assign_iterable_with)
