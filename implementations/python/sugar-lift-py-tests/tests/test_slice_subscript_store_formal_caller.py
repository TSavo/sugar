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
from sugar_lift_py_tests.floor import ListValue, SliceValue, TermValue, TupleValue
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
    site = _site()
    out = SliceSugar(
        _FloorSugar(TermValue(1)),
        _FloorSugar(TermValue(3)),
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


# ---------------------------------------------------------------------------
# Production SubscriptStoreEffectSugar + SliceSugar path
# ---------------------------------------------------------------------------


def test_production_store_sugar_with_slice_index_completes() -> None:
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
            _FloorSugar(TermValue(0)), _FloorSugar(TermValue(2)), None, site
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
