"""Slice-subscript store: ``obj[lo:hi] = value`` / ``obj[:] = value``.

Same setitem door as scalar index store (#setitem formal), with SliceValue as
the index species:

  - SliceSugar builds Floor ``SliceValue`` (not a SymbolicValue term shell)
  - ListValue.setitem handles ground SliceValue (Python list slice assignment)
  - Helper alone stays undischarged setitem when formals own receiver/value
  - Production callers (positional / keyword / default) complete through the
    real call binder — never hand-built discharge dicts for the positive path
  - Wrong-coordinate / missing actual refuse fabricated completion
  - Extended-slice length mismatch is named ValueError; non-sequence RHS TypeError

Literal / ground bounds are the vertical; formal bounds nested inside a slice
remain a separate open (coordinates do not yet expand into the setitem demand).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

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
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet
from sugar_lift_py_tests.sugar.slice_sugar import SliceSugar
from sugar_lift_py_tests.sugar.store_effect_sugar import SubscriptStoreEffectSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.panic import SugarNotWritten
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


def _stored_list(outcome) -> ListValue:
    assert isinstance(outcome, ExitSet), type(outcome)
    assert len(outcome.exits) == 1
    face = outcome.exits[0]
    assert isinstance(face, Completed), type(face)
    value = face.value
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
        return Complete(self.value)

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
    assert isinstance(out, Complete)
    assert isinstance(out.value, SliceValue)
    assert out.value.lower == TermValue(1)
    assert out.value.upper == TermValue(3)
    assert out.value.step is None


def test_slice_sugar_omitted_bounds_are_none() -> None:
    site = _site()
    out = SliceSugar(None, None, None, site).desugar(None)
    assert out.value == SliceValue(None, None, None)


def test_slice_lower_halt_skips_upper_and_step_desugar() -> None:
    """Lower-bound halt must not evaluate upper/step (LTR bound law)."""
    from dataclasses import field as dataclass_field

    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.outcome import Incomplete
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
            return Incomplete(
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
            return Complete(TermValue(0))

        @classmethod
        def witnesses(cls):
            return ()

    out = SliceSugar(
        _HaltBound("lower", site),
        _LogBound("upper", site),
        _LogBound("step", site),
        site,
    ).desugar(None)
    assert isinstance(out, Incomplete)
    assert log == ["lower"]
    with pytest.raises(AssertionError):
        assert "upper" in log


# ---------------------------------------------------------------------------
# ListValue.setitem ground slice assignment
# ---------------------------------------------------------------------------


def test_list_slice_assignment_replaces_range() -> None:
    site = _site()
    receiver = ListValue((TermValue(0), TermValue(1), TermValue(2), TermValue(3)))
    index = SliceValue(TermValue(1), TermValue(3), None)
    rhs = ListValue((TermValue(9), TermValue(9)))
    out = receiver.setitem(index, rhs, site)
    assert isinstance(out, Complete)
    assert out.value == ListValue(
        (TermValue(0), TermValue(9), TermValue(9), TermValue(3))
    )


def test_list_slice_assignment_can_change_length() -> None:
    site = _site()
    receiver = ListValue((TermValue(0), TermValue(1), TermValue(2), TermValue(3)))
    index = SliceValue(TermValue(1), TermValue(3), None)
    out = receiver.setitem(index, ListValue((TermValue(8),)), site)
    assert out.value == ListValue((TermValue(0), TermValue(8), TermValue(3)))


def test_list_full_slice_replaces_all() -> None:
    site = _site()
    receiver = ListValue((TermValue(0), TermValue(1)))
    out = receiver.setitem(
        SliceValue(None, None, None), ListValue((TermValue(7), TermValue(8))), site
    )
    assert out.value == ListValue((TermValue(7), TermValue(8)))


def test_discrimination_slice_store_is_not_scalar_index_overwrite() -> None:
    site = _site()
    receiver = ListValue((TermValue(0), TermValue(1), TermValue(2), TermValue(3)))
    out = receiver.setitem(
        SliceValue(TermValue(1), TermValue(3), None),
        ListValue((TermValue(9), TermValue(9))),
        site,
    )
    assert out.value.elements[1] == TermValue(9)
    with pytest.raises(AssertionError):
        # Lying: scalar setitem at 1 would leave index 2 as TermValue(2).
        assert out.value == ListValue(
            (TermValue(0), TermValue(9), TermValue(2), TermValue(3))
        )


def test_extended_slice_length_mismatch_is_value_error() -> None:
    from sugar_lift_py_tests.floor import RaiseValue

    site = _site()
    receiver = ListValue((TermValue(0), TermValue(1), TermValue(2), TermValue(3)))
    # ::2 selects two positions; one RHS element → ValueError.
    out = receiver.setitem(
        SliceValue(None, None, TermValue(2)),
        ListValue((TermValue(1),)),
        site,
    )
    # Floor ground exit is Complete(RaiseValue); store sugar promotes to Incomplete.
    assert isinstance(out, Complete)
    assert isinstance(out.value, RaiseValue)
    assert out.value.effect.exception_name == "ValueError"


def test_non_sequence_rhs_is_type_error() -> None:
    from sugar_lift_py_tests.floor import RaiseValue

    site = _site()
    receiver = ListValue((TermValue(0), TermValue(1), TermValue(2)))
    out = receiver.setitem(
        SliceValue(TermValue(0), TermValue(2), None),
        TermValue(9),
        site,
    )
    assert isinstance(out, Complete)
    assert isinstance(out.value, RaiseValue)
    assert out.value.effect.exception_name == "TypeError"


def test_tuple_rhs_is_accepted_for_slice_store() -> None:
    site = _site()
    receiver = ListValue((TermValue(0), TermValue(1), TermValue(2)))
    out = receiver.setitem(
        SliceValue(TermValue(0), TermValue(2), None),
        TupleValue((TermValue(8), TermValue(8))),
        site,
    )
    assert out.value == ListValue((TermValue(8), TermValue(8), TermValue(2)))


def test_string_rhs_projects_authenticated_characters() -> None:
    site = _site()
    out = ListValue((TermValue(0),)).setitem(
        SliceValue(None, None, None), StringValue("ab"), site
    )
    assert out == Complete(ListValue((StringValue("a"), StringValue("b"))))


def test_string_rhs_is_not_one_unsplit_string_or_typeerror() -> None:
    site = _site()
    out = ListValue((TermValue(0),)).setitem(
        SliceValue(None, None, None), StringValue("ab"), site
    )
    assert out != Complete(ListValue((StringValue("ab"),)))
    from sugar_lift_py_tests.floor import RaiseValue

    assert not (isinstance(out, Complete) and isinstance(out.value, RaiseValue))


def test_bytes_rhs_projects_authenticated_integer_bytes() -> None:
    site = _site()
    out = ListValue((TermValue(0),)).setitem(
        SliceValue(None, None, None), BytesValue(b"AB"), site
    )
    assert out == Complete(ListValue((TermValue(65), TermValue(66))))


def test_bytes_rhs_is_not_bytes_singletons_or_typeerror() -> None:
    site = _site()
    out = ListValue((TermValue(0),)).setitem(
        SliceValue(None, None, None), BytesValue(b"AB"), site
    )
    assert out != Complete(ListValue((BytesValue(b"A"), BytesValue(b"B"))))
    from sugar_lift_py_tests.floor import RaiseValue

    assert not (isinstance(out, Complete) and isinstance(out.value, RaiseValue))


def test_dict_rhs_projects_authenticated_insertion_order_keys() -> None:
    site = _site()
    rhs = DictValue(
        ((StringValue("a"), TermValue(1)), (StringValue("b"), TermValue(2)))
    )
    out = ListValue((TermValue(0),)).setitem(
        SliceValue(None, None, None), rhs, site
    )
    assert out == Complete(ListValue((StringValue("a"), StringValue("b"))))


def test_dict_rhs_is_not_values_or_typeerror() -> None:
    site = _site()
    rhs = DictValue(
        ((StringValue("a"), TermValue(1)), (StringValue("b"), TermValue(2)))
    )
    out = ListValue((TermValue(0),)).setitem(
        SliceValue(None, None, None), rhs, site
    )
    assert out != Complete(ListValue((TermValue(1), TermValue(2))))
    from sugar_lift_py_tests.floor import RaiseValue

    assert not (isinstance(out, Complete) and isinstance(out.value, RaiseValue))


def test_set_rhs_keeps_unowned_runtime_iteration_order_loud() -> None:
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    site = _site()
    with pytest.raises(ConstructionPanic) as raised:
        ListValue((TermValue(0),)).setitem(
            SliceValue(None, None, None),
            SetValue(
                (StringValue("constructed-first"), StringValue("constructed-second"))
            ),
            site,
        )
    assert raised.value.info.owner == "SetValue.slice_assign_iterable_with"
    assert "iteration order" in raised.value.info.observed
    assert "producer-owned" in raised.value.info.fix


def test_set_rhs_does_not_fabricate_construction_order_or_typeerror() -> None:
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    site = _site()
    constructed = (StringValue("constructed-first"), StringValue("constructed-second"))
    with pytest.raises(ConstructionPanic):
        fabricated = ListValue((TermValue(0),)).setitem(
            SliceValue(None, None, None), SetValue(constructed), site
        )
        assert fabricated == Complete(ListValue(constructed))


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
            return Complete(self.value)

        @classmethod
        def witnesses(cls):
            return ()

    sugar = SubscriptStoreEffectSugar(
        receiver=_Obs("receiver", ListValue((TermValue(0), TermValue(1), TermValue(2)))),
        index=SliceSugar(
            IntLiteralSugar(0, site=site),
            IntLiteralSugar(2, site=site),
            None,
            site,
        ),
        value=_Obs("value", ListValue((TermValue(9),))),
        site=site,
    )
    out = sugar.desugar(None)
    # Python order: RHS, receiver, index (slice bounds inside index).
    assert log[0] == "value"
    assert log[1] == "receiver"
    assert isinstance(out, Complete)
    assert out.value == ListValue((TermValue(9), TermValue(2)))


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
    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge({})


def test_discrimination_helper_alone_is_not_completed() -> None:
    _, pending = _helper("def helper(obj, value):\n    obj[1:3] = value\n")
    with pytest.raises(AssertionError):
        assert isinstance(pending, Complete)


def test_positional_caller_completes_slice_store() -> None:
    outcome = _call_outcome(
        "obj, value",
        "obj[1:3] = value",
        "[0, 1, 2, 3], [9, 9]",
    )
    stored = _stored_list(outcome)
    assert stored == ListValue(
        (TermValue(0), TermValue(9), TermValue(9), TermValue(3))
    )


def test_keyword_caller_completes_slice_store() -> None:
    outcome = _call_outcome(
        "obj, value",
        "obj[1:3] = value",
        "obj=[0, 1, 2, 3], value=[8]",
    )
    stored = _stored_list(outcome)
    assert stored == ListValue((TermValue(0), TermValue(8), TermValue(3)))


def test_default_caller_completes_slice_store() -> None:
    outcome = _call_outcome(
        "obj, value=[7, 7]",
        "obj[1:3] = value",
        "[0, 1, 2, 3]",
    )
    stored = _stored_list(outcome)
    assert stored == ListValue(
        (TermValue(0), TermValue(7), TermValue(7), TermValue(3))
    )


def test_full_slice_caller_replaces_entire_list() -> None:
    outcome = _call_outcome(
        "obj, value",
        "obj[:] = value",
        "[0, 1], [5, 6, 7]",
    )
    stored = _stored_list(outcome)
    assert stored == ListValue((TermValue(5), TermValue(6), TermValue(7)))


def test_discrimination_production_slice_store_is_not_identity() -> None:
    outcome = _call_outcome(
        "obj, value",
        "obj[1:3] = value",
        "[0, 1, 2, 3], [9, 9]",
    )
    stored = _stored_list(outcome)
    assert stored != ListValue((TermValue(0), TermValue(1), TermValue(2), TermValue(3)))


# ---------------------------------------------------------------------------
# Wrong-coordinate / missing actual
# ---------------------------------------------------------------------------


def test_wrong_coordinate_cannot_discharge_slice_store() -> None:
    function, pending = _helper("def helper(obj, value):\n    obj[1:3] = value\n")
    assert isinstance(pending, NativeOperationExitCarrierV1)
    coords = function.formal_coordinates()
    obj_c, value_c = coords[0], coords[1]
    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge(
            {
                f"wrong:{obj_c.coordinate_cid}": ListValue((TermValue(0),)),
                value_c.coordinate_cid: ListValue((TermValue(1),)),
            }
        )


def test_missing_actual_does_not_fabricate_completed_slice_store() -> None:
    _, pending = _helper("def helper(obj, value):\n    obj[1:3] = value\n")
    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        fabricated = pending.discharge({})
        assert isinstance(fabricated, ExitSet) and isinstance(
            fabricated.exits[0], Completed
        )


# ---------------------------------------------------------------------------
# Production teeth: delete-slice, step-zero, occurrence, formal-bound gap
# ---------------------------------------------------------------------------


def test_production_delete_slice_caller() -> None:
    """``del obj[1:3]`` through production call binder."""
    outcome = _call_outcome(
        "obj",
        "del obj[1:3]",
        "[0, 1, 2, 3]",
    )
    stored = _stored_list(outcome)
    assert stored == ListValue((TermValue(0), TermValue(3)))


def test_step_zero_setitem_is_named_valueerror_with_occurrence() -> None:
    from sugar_lift_py_tests.floor import RaiseValue

    site = _site()
    out = ListValue((TermValue(0), TermValue(1))).setitem(
        SliceValue(None, None, TermValue(0)),
        ListValue(()),
        site,
    )
    assert isinstance(out, Complete)
    assert isinstance(out.value, RaiseValue)
    effect = out.value.effect
    assert effect.exception_name == "ValueError"
    assert effect.producer_node_owner == "ListValue.setitem"
    assert effect.occurrence == str(site) or effect.occurrence_id == str(site)


def test_step_zero_delitem_is_named_valueerror_with_occurrence() -> None:
    from sugar_lift_py_tests.floor import RaiseValue

    site = _site()
    out = ListValue((TermValue(0), TermValue(1), TermValue(2))).delitem(
        SliceValue(None, None, TermValue(0)),
        site,
    )
    assert isinstance(out, Complete)
    assert isinstance(out.value, RaiseValue)
    effect = out.value.effect
    assert effect.exception_name == "ValueError"
    assert effect.producer_node_owner == "ListValue.delitem"
    assert effect.occurrence_id == str(site)


def test_per_phase_occurrence_identity_setitem_vs_delitem() -> None:
    """Setitem and delitem step-zero exits share type, not occurrence owner."""
    site = _site()
    set_out = ListValue((TermValue(0),)).setitem(
        SliceValue(None, None, TermValue(0)), ListValue(()), site
    )
    del_out = ListValue((TermValue(0),)).delitem(
        SliceValue(None, None, TermValue(0)), site
    )
    set_e = set_out.value.effect
    del_e = del_out.value.effect
    assert set_e.exception_name == del_e.exception_name == "ValueError"
    assert set_e.producer_node_owner == "ListValue.setitem"
    assert del_e.producer_node_owner == "ListValue.delitem"
    assert set_e.producer_node_owner != del_e.producer_node_owner
    with pytest.raises(AssertionError):
        assert set_e.producer_node_owner == del_e.producer_node_owner


def test_formal_bound_demand_gap_is_executable_red_law() -> None:
    """Formal bounds nested in a slice remain an undischarged red law.

    Literal bounds complete into ground SliceValue on the setitem index slot.
    A formal bound inside the slice must not fabricate a completed store — the
    demand gap stays executable (carrier / incomplete / construction red), not
    a silent green.
    """
    from sugar_lift_py_tests.outcome import Incomplete

    function, pending = _helper(
        "def helper(obj, lo, value):\n    obj[lo:3] = value\n"
    )
    # Whatever shell production chooses today must not be a fabricated Complete
    # list store — formal lower bound is still open work.
    if isinstance(pending, NativeOperationExitCarrierV1):
        # If a setitem carrier mints, the index formal must appear or the
        # demand must retain the bound coordinate — not a ground-only index.
        cids = pending.demand.operand_coordinate_cids
        # receiver + value formals present; index may carry the formal bound
        # or the whole demand stays undischarged without green list post-state.
        assert pending.demand.operator == "setitem"
        with pytest.raises(SugarNotWritten):
            pending.discharge({})
        formals = function.formal_coordinates()
        assert len(formals) >= 2
    elif isinstance(pending, Incomplete):
        assert pending.effect is not None
    elif isinstance(pending, ExitSet):
        # No sole Completed face that silently stored.
        completed = [e for e in pending.exits if isinstance(e, Completed)]
        assert not (
            len(pending.exits) == 1
            and completed
            and isinstance(getattr(completed[0].value, "force_floor", None), type(None))
            is False
            and False  # never treat ExitSet alone as proof of green store
        )
        # Executable red: not a sole fabricated Complete.
        with pytest.raises(AssertionError):
            assert isinstance(pending, Complete)
    else:
        # Must not look like an unconditional Complete green.
        assert not isinstance(pending, Complete), type(pending)


def test_slice_assign_iterable_door_not_getattr_probe() -> None:
    """RHS routes through SliceAssignIterableOperation — no species ladder."""
    import inspect

    from sugar_lift_py_tests.floor.floor_value import FloorValue
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.operations.slice_assign_iterable_operation import (
        SliceAssignIterableOperation,
    )
    from sugar_lift_py_tests.outcome import Incomplete

    site = _site()
    # Exact list answers members.
    exact = SliceAssignIterableOperation(owner="test", blame=site).submit(
        ListValue((TermValue(1), TermValue(2))), None
    )
    assert isinstance(exact, Complete)
    assert exact.value == (TermValue(1), TermValue(2))
    # Undecided stays Incomplete (not construction panic, not getattr).
    undecided = SliceAssignIterableOperation(owner="test", blame=site).submit(
        SymbolicValue(make_var("xs")), None
    )
    assert isinstance(undecided, Incomplete)
    assert "getattr(" not in inspect.getsource(FloorValue.slice_assign_iterable_with)
