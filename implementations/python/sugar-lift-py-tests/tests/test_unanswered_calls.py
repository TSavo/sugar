"""Unanswered calls ride the arms' ``owed`` slot (PR B on #7766; #7825, H4).

``UnknownCalleeCallV1.faces`` puts one ``UnansweredCallV1`` on BOTH its
arms. ``owed`` is carried by union at every
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
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    complement_guard,
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
    sequenced = _call_arms(item).and_then(lambda value: ExitSet.completed(TermValue(2)))
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
    # The debt rides the arm; an arm that owes nothing carries none.
    assert owing.owed_items() == (item,)
    assert ExitSet.completed(TermValue(1)).owed_items() == ()


def test_owed_items_keeps_every_debt_once_in_first_seen_order() -> None:
    first = unanswered_calls.unanswered_call("a", _Site())
    second = unanswered_calls.unanswered_call(None, _Site())
    arms = ExitSet(
        (
            Completed(atomic("test:a", []), TermValue(1), owed=(first,)),
            Completed(atomic("test:b", []), TermValue(2)),
            Completed(atomic("test:c", []), TermValue(3), owed=(second, first)),
        )
    )
    assert arms.owed_items() == (first, second)
    assert ExitSet((Completed(true_guard(), TermValue(1)),)).owed_items() == ()


def test_owed_union_is_private_to_the_exit_algebra() -> None:
    """#7825: one composition. Debts are carried by ``sequence`` / ``union``."""
    from sugar_lift_py_tests.outcome import exit_set

    assert not hasattr(exit_set, "owed_union")
    assert "owed_union" not in exit_set.__all__


def test_an_arm_with_no_debt_owes_nothing() -> None:
    assert unanswered_calls.owed_calls(ExitSet.completed(TermValue(1))) == ()


def test_a_call_without_a_site_is_loud_where_it_would_become_a_member() -> None:
    siteless = unanswered_calls.unanswered_call(None, None)
    with pytest.raises(ValueError, match="no site"):
        _tree.unanswered_call_rows((siteless,), "m.py")


class _ImportedCall:
    """A call the import door authenticated, with its target symbol."""

    authenticated_target_symbol = "python:zlib.crc32"


def test_an_unanswered_call_is_owed_by_both_arms() -> None:
    # "Not bridged" is stated one way: an unknown callee, or a callee cited
    # off the enrolled population, is one `UnknownCalleeCallV1`, owed by both
    # arms of its two-faced call.
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

    faces = UnknownCalleeCallV1("zlib.crc32").faces(_ImportedCall(), _Site())
    expected = (unanswered_calls.UnansweredCallV1("python:zlib.crc32", _COORDINATE),)
    assert len(faces.exits) == 2
    assert all(exit_.owed == expected for exit_ in faces.exits)
    assert unanswered_calls.owed_calls(faces) == expected


def test_an_off_population_call_is_the_unanswered_call() -> None:
    # The cited-off-population producer makes no second kind of call.
    from sugar_lift_py_tests import source_call_resolution
    from sugar_lift_py_tests.sugar.call_site_sugar import (
        CallSiteSugar,
        _off_population_unanswered_call,
    )

    assert not hasattr(source_call_resolution, "OffPopulationSourceCallV1")
    sugar = CallSiteSugar(
        target_name="crc32",
        args=(),
        site=_Site(),
        contract_resolution_gap="call-target-off-population:python:zlib.crc32",
        reference_symbol="zlib.crc32",
    )
    unanswered = _off_population_unanswered_call(sugar)
    assert unanswered == source_call_resolution.UnknownCalleeCallV1("zlib.crc32")


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
