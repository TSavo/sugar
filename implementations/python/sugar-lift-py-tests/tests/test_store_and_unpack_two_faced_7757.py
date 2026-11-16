"""A store and a runtime unpack are two-faced through the one constructor.

#7757 item 13, the two leftovers of #8085. ``ExitSet.two_faced`` is the one
constructor of "completes under this atom, or raises something undetermined
under its complement", and it owes the operation as the one ``undecided``
member (reason ``unanswered``).

- An item store or delete nothing decides -- on a receiver whose type is
  undecided, or on a decided ``list`` / ``dict`` whose index, key, slice
  bound or right-hand side is not decided -- is the one undecided item
  mutation (``undecided_item_mutation_faces``, #7757 NEW-9; the attribute
  side is ``undecided_attribute_mutation_faces``, NEW-4).  Its exception
  class is not one known class, so it is two-faced: it completes, under
  its completes atom keyed per evaluation, with the receiver after it
  unknown, raises ``UndeterminedRaiseEffect`` under the complement, and
  owes its site.  The per-site ``store_faces`` testimony it replaces is
  deleted.
- An unpack of a value with no authenticated cardinality
  (``runtime_unpack_faces``) raises ``ValueError`` on a count mismatch,
  ``TypeError`` on a non-iterable, or whatever ``__iter__`` raises, under an
  opaque ``python:unpack.completes`` atom -- not a decided formula over a
  known length. So it is two-faced too, and its halt is the one undetermined
  raise; ``SequenceUnpackRuntimeEffect`` (a second effect type for the same
  meaning) is deleted. A DECIDED length never comes here and owes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from frame_fresh import fresh

import sugar_lift_py_tests.effect as effect_module
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.dict_value import DictValue
from sugar_lift_py_tests.floor.list_value import ListValue
from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.ir import atomic, ctor, make_var, str_const
from sugar_lift_py_tests.occurrence import occurrence_key
from sugar_lift_py_tests.operations import SequenceProjectionOperation
from sugar_lift_py_tests.operations.positional_unpack_operation import (
    PositionalUnpackOperation,
)
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted, complement_guard
from sugar_lift_py_tests.unanswered_calls import UnansweredCallV1, owed_calls

_SRC = "blake3-512:" + "cd" * 64


@dataclass(frozen=True)
class _Span:
    start_line: int = 3
    start_col: int = 4
    end_line: int = 3
    end_col: int = 12


@dataclass(frozen=True)
class _Site:
    """A fragment's runtime locus (filename/line/col) and its two coordinates
    (its unit's source CID and its span)."""

    filename: str = "pkg/m.py"
    line: int = 3
    col: int = 4
    source_cid: str = _SRC
    line_col_span: _Span = _Span()


_COORDINATE = SourceFragmentCoordinateV1(_SRC, 3, 4, 3, 12)
_OWED = (UnansweredCallV1(None, _COORDINATE),)


def _faces(outcome):
    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    (halt,) = [arm for arm in outcome.exits if isinstance(arm, Halted)]
    assert len(outcome.exits) == 2
    return done, halt


def _assert_undetermined_and_owed(outcome, owner: str):
    """Completes under ``g``, raises something undetermined under its
    complement, and both arms owe the operation once, at its site."""
    done, halt = _faces(outcome)
    assert halt.guard == complement_guard(done.guard)
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.effect.exception_type_coordinate is None
    assert halt.effect.producer_node_owner == owner
    assert done.owed == halt.owed == _OWED
    assert owed_calls(outcome) == _OWED
    return done, halt


def _list_store(site=None):
    """``xs[i] = 9`` on a decided list whose index nothing decides: the one
    undecided item mutation (#7757 NEW-9), the spelling a store over an
    undecided receiver already takes."""
    xs = fresh(ListValue, (TermValue(1), TermValue(2)))
    return xs.setitem(
        SymbolicValue(make_var("i")),
        TermValue(9),
        site if site is not None else _Site(),
        None,
    )


def _undecided_mutation(site, method: str):
    """The completed value and guard of the one undecided item mutation at
    ``site``: the receiver after THIS evaluation, unknown, under its own
    completes atom, both keyed by the evaluation's occurrence."""
    key = occurrence_key(site)
    noun = method.strip("_")
    after = SymbolicValue(
        ctor("python:receiver_after_call", (str_const(key), str_const(method)))
    )
    guard = atomic(
        f"python:{noun}.completes", [ctor(f"python:{noun}", (str_const(key),))]
    )
    return after, guard


# ---------------------------------------------------------------------------
# (1) the store
# ---------------------------------------------------------------------------


def test_a_store_is_two_faced_and_owes_its_site() -> None:
    site = _Site()
    done, _halt = _assert_undetermined_and_owed(_list_store(site), "ListValue.setitem")
    # The completed face is the receiver after THIS store, unknown: no reader
    # takes the list as unchanged, and nothing is read off it.
    after, guard = _undecided_mutation(site, "__setitem__")
    assert done.value == after
    assert done.guard == guard
    assert not isinstance(done.value, ListValue)


def test_a_delete_whose_key_is_not_decided_is_the_same_mutation() -> None:
    site = _Site()
    receiver = fresh(DictValue, ((StringValue("k"), TermValue(1)),))
    outcome = receiver.delitem(SymbolicValue(make_var("k")), site, None)
    done, _halt = _assert_undetermined_and_owed(outcome, "DictValue.delitem")
    after, guard = _undecided_mutation(site, "__delitem__")
    assert done.value == after
    assert done.guard == guard


def test_a_decided_containers_undecided_store_is_the_one_spelling() -> None:
    """One way (#7757 NEW-9): the decided list's undecided store is
    ``undecided_item_mutation_faces``, the same faces an undecided
    receiver's store is, never a second per-site testimony."""
    from sugar_lift_py_tests.sugar.store_effect_sugar import (
        undecided_item_mutation_faces,
    )

    site = _Site()
    assert _list_store(site) == undecided_item_mutation_faces(
        site, method="__setitem__", owner="ListValue.setitem"
    )


def test_two_stores_owe_two_sites() -> None:
    """Discrimination: the debt is the store's own site, not a shared one."""
    other_site = _Site(line=5, line_col_span=_Span(5, 0, 5, 7))
    first = owed_calls(_list_store())
    second = owed_calls(_list_store(other_site))
    assert first == _OWED
    assert second == (
        UnansweredCallV1(None, SourceFragmentCoordinateV1(_SRC, 5, 0, 5, 7)),
    )
    assert first != second


# ---------------------------------------------------------------------------
# (2) the runtime unpack
# ---------------------------------------------------------------------------


def test_a_positional_runtime_unpack_is_two_faced_and_owes_its_site() -> None:
    operation = PositionalUnpackOperation(
        fixed_prefix=2, fixed_suffix=0, has_star=False, owner="twin", blame=_Site()
    )
    done, halt = _assert_undetermined_and_owed(
        operation.submit(SymbolicValue(make_var("xs")), None), "twin.unpack"
    )
    assert len(done.value.members) == 2
    assert "python:unpack.completes" in str(done.guard)
    assert "python:unpack.destructure" in str(done.guard)


def test_a_named_runtime_unpack_is_two_faced_and_owes_its_site() -> None:
    operation = SequenceProjectionOperation(
        target_names=("a", "b"), owner="twin", blame=_Site()
    )
    done, _ = _assert_undetermined_and_owed(
        operation.submit(SymbolicValue(make_var("xs")), None), "twin.unpack"
    )
    assert isinstance(done.value, ScopeRebinds)
    assert tuple(name for name, _ in done.value.bindings) == ("a", "b")


def test_a_decided_length_is_not_two_faced_and_owes_nothing() -> None:
    """Discrimination: a tuple's length is a fact about the input, so its
    unpack is answered outright -- no undetermined raise, no debt."""
    operation = SequenceProjectionOperation(
        target_names=("a", "b"), owner="twin", blame=_Site()
    )
    outcome = operation.submit(
        TupleLiteralValue((TermValue(1), TermValue(2))), None
    )
    assert outcome.completed_value() == ScopeRebinds(
        (("a", TermValue(1)), ("b", TermValue(2)))
    )
    assert outcome.halts() == ()
    assert owed_calls(outcome) == ()


def test_a_prose_unpack_site_is_still_refused() -> None:
    operation = PositionalUnpackOperation(
        fixed_prefix=2, fixed_suffix=0, has_star=False, owner="twin", blame="prose"
    )
    with pytest.raises(TypeError, match="fragment"):
        operation.submit(SymbolicValue(make_var("xs")), None)


def test_the_second_unpack_effect_type_is_deleted() -> None:
    assert not hasattr(effect_module, "SequenceUnpackRuntimeEffect")
    assert "SequenceUnpackRuntimeEffect" not in effect_module.__all__
