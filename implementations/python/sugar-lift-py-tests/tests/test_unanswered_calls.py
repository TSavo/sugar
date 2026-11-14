"""Unanswered calls ride the arms' ``owed`` slot (PR B on #7766; #7825, H4).

``UnknownCalleeCallV1.faces`` and ``OffPopulationSourceCallV1.faces`` put one
``UnansweredCallV1`` on BOTH their arms. ``owed`` is carried by union at every
arm rebuild, never decides a merge, and the full scan reads it off the
reduction's final arms (``unanswered_calls.owed_calls``). There is no
collector.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests import tree_enumerate as _tree
from sugar_lift_py_tests import unanswered_calls
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.ir import atomic
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    complement_guard,
    owed_union,
    true_guard,
)

_SRC = "blake3-512:" + "ab" * 64


class _Site:
    """A fragment's two coordinates: its unit's source CID and its span."""

    class _Span:
        start_line, start_col, end_line, end_col = 5, 11, 5, 19

    source_cid = _SRC
    line_col_span = _Span()


_COORDINATE = SourceFragmentCoordinateV1(_SRC, 5, 11, 5, 19)


def _call_arms(item, value=1):
    """The two arms an unknown callee call produces, both owing ``item``."""
    completes = atomic("test:completes", [])
    return ExitSet(
        (
            Completed(completes, TermValue(value), owed=(item,)),
            Halted(
                complement_guard(completes),
                UndeterminedRaiseEffect(blame="test", occurrence="test"),
                None,
                owed=(item,),
            ),
        )
    ).normalize()


def test_the_owed_item_names_symbol_and_coordinate() -> None:
    item = unanswered_calls.unanswered_call("python:idn.ident", _Site())
    assert item == unanswered_calls.UnansweredCallV1("python:idn.ident", _COORDINATE)
    assert unanswered_calls.unanswered_call(None, None).site is None


def test_owed_never_decides_equality_or_a_merge() -> None:
    item = unanswered_calls.unanswered_call(None, _Site())
    plain = Completed(atomic("test:g", []), TermValue(1))
    owing = Completed(atomic("test:g", []), TermValue(1), owed=(item,))
    assert plain == owing
    merged = ExitSet((plain, owing)).normalize()
    assert len(merged.exits) == 1
    assert merged.owed_items() == (item,)


def test_sequence_carries_the_prefix_debt_onto_every_continuation() -> None:
    item = unanswered_calls.unanswered_call("python:idn.ident", _Site())
    sequenced = _call_arms(item).and_then(lambda value: Complete(TermValue(2)))
    assert sequenced.exits
    assert all(exit_.owed == (item,) for exit_ in sequenced.exits)
    assert unanswered_calls.owed_calls(sequenced) == (item,)


def test_an_owing_arm_is_never_collapsed_to_a_linear_outcome() -> None:
    item = unanswered_calls.unanswered_call(None, _Site())
    owing = ExitSet.completed(TermValue(1)).sequence(
        lambda value: ExitSet((Completed(true_guard(), value, owed=(item,)),))
    )
    assert isinstance(owing.collapse(), ExitSet)
    assert owing.completed_value() == TermValue(1)
    assert isinstance(ExitSet.completed(TermValue(1)).collapse(), Complete)


def test_owed_union_keeps_every_debt_once_in_first_seen_order() -> None:
    first = unanswered_calls.unanswered_call("a", _Site())
    second = unanswered_calls.unanswered_call(None, _Site())
    assert owed_union((first,), (), (second, first)) == (first, second)
    assert owed_union((), ()) == ()


def test_a_linear_outcome_owes_nothing() -> None:
    assert unanswered_calls.owed_calls(Complete(TermValue(1))) == ()


def test_a_call_without_a_site_is_loud_where_it_would_become_a_member() -> None:
    siteless = unanswered_calls.unanswered_call(None, None)
    with pytest.raises(ValueError, match="no site"):
        _tree.unanswered_call_rows((siteless,), "m.py")


class _ImportedCall:
    """A call the import door authenticated, with its target symbol."""

    authenticated_target_symbol = "python:zlib.crc32"


def test_an_off_population_call_is_owed_like_an_unknown_callee() -> None:
    # "Not bridged" is stated one way: a callee cited off the enrolled
    # population is the same `undecided` member as an unknown callee, owed by
    # both arms of its two-faced call.
    from sugar_lift_py_tests.source_call_resolution import (
        OffPopulationSourceCallV1,
        UnknownCalleeCallV1,
    )

    off_population = OffPopulationSourceCallV1("python:zlib.crc32").faces(
        _ImportedCall(), _Site()
    )
    unknown = UnknownCalleeCallV1("crc32").faces(_ImportedCall(), _Site())
    expected = (unanswered_calls.UnansweredCallV1("python:zlib.crc32", _COORDINATE),)
    for faces in (off_population, unknown):
        assert len(faces.exits) == 2
        assert all(exit_.owed == expected for exit_ in faces.exits)
        assert unanswered_calls.owed_calls(faces) == expected


def test_one_row_per_distinct_symbol_and_site() -> None:
    other = SourceFragmentCoordinateV1(_SRC, 6, 4, 6, 9)
    calls = [
        unanswered_calls.UnansweredCallV1("python:idn.ident", _COORDINATE),
        # the same call reduced twice
        unanswered_calls.UnansweredCallV1("python:idn.ident", _COORDINATE),
        unanswered_calls.UnansweredCallV1(None, other),
    ]
    rows = [
        row.to_rpc_with_term_table(None)
        for row in _tree.unanswered_call_rows(calls, "m.py")
    ]
    assert rows == [
        {
            "kind": "undecided",
            "symbol": "python:idn.ident",
            "site": {"file": "m.py", **_COORDINATE.wire()},
            "reason": {"unanswered": {}},
        },
        {
            "kind": "undecided",
            "symbol": None,
            "site": {"file": "m.py", **other.wire()},
            "reason": {"unanswered": {}},
        },
    ]
