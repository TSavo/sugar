import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    DictValue,
    GuardedValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import atomic, make_var, not_
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted


def _store(receiver, index, value):
    return receiver.setitem(index, value, "store-site", None)


class _Site:
    """A fragment's two coordinates: the undecided mutation keys its
    completes atom and its owed member on them."""

    class _Span:
        start_line, start_col, end_line, end_col = 3, 4, 3, 12

    source_cid = "blake3-512:" + "ef" * 64
    line_col_span = _Span()


def _undecided_arm(kind: str):
    """A receiver arm whose type nothing here decides."""
    if kind == "symbolic":
        return SymbolicValue(make_var("xs"))
    return CallSiteValue(
        target_name="make",
        arg_values=(),
        parameters=(),
        term=make_var("made"),
        body=None,
        site="make-call",
    )


def _undetermined_halts(outcome):
    halts = [face for face in outcome.exits if isinstance(face, Halted)]
    return [face for face in halts if isinstance(face.effect, UndeterminedRaiseEffect)]


@pytest.mark.parametrize("kind", ("symbolic", "callsite"))
@pytest.mark.parametrize("method", ("setitem", "delitem"))
def test_a_guarded_receiver_s_undecided_arm_keeps_its_halt(
    kind: str, method: str
) -> None:
    """``d[k] = v`` / ``del d[k]`` where ``d`` is a guarded choice between an
    undecided value and a dict: the undecided arm stores through the one item
    mutation, so it raises something undetermined under its own polarity and
    completes only under its own completes atom.  Before, the distribution
    called the arm's own ``setitem``/``delitem``, which completed with no
    halt face: the claim "this store always completes" stood (#7757 step 7).

    The dict arm holds ``k``, so its own delete completes: ``del {}["k"]`` is
    the ground ``KeyError``, whose exit cites a fragment it can re-read, and
    ``_Site`` states no source to cite (that arm's refusal is the lifter's
    right answer, not this test's subject)."""
    guard = atomic("selected", [])
    receiver = GuardedValue(
        guard,
        _undecided_arm(kind),
        fresh(DictValue, ((StringValue("k"), TermValue(1)),)),
    )
    if method == "setitem":
        outcome = receiver.setitem(StringValue("k"), TermValue(7), _Site(), None)
        owner = "UndecidedSetitem"
    else:
        outcome = receiver.delitem(StringValue("k"), _Site(), None)
        owner = "UndecidedDelitem"

    undetermined = _undetermined_halts(outcome)
    (halt,) = undetermined
    assert halt.effect.producer_node_owner == owner
    assert "selected" in str(halt.guard)
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    # The undecided arm never completes under its selecting guard alone.
    assert guard not in {face.guard for face in completed}
    assert any(f"python:{method}.completes" in str(face.guard) for face in completed)


def test_a_guarded_receiver_and_a_guarded_index_keep_the_undecided_halt() -> None:
    """A guarded index split over a guarded receiver with an undecided arm:
    each partition stays a sibling under its own polarity (the one rejoin
    rule ``_map`` and ``_map_over`` share), never a refusal for the
    partition and never a single completion."""
    receiver = GuardedValue(
        atomic("receiver", []), _undecided_arm("symbolic"), fresh(DictValue, ())
    )
    index = GuardedValue(atomic("index", []), StringValue("a"), StringValue("b"))

    outcome = receiver.setitem(index, TermValue(7), _Site(), None)

    undetermined = _undetermined_halts(outcome)
    assert undetermined
    assert all(
        face.effect.producer_node_owner == "UndecidedSetitem" for face in undetermined
    )
    assert outcome.completed_value() is None


def _entry_map(value):
    return {key.value: item.value for key, item in value.entries}


def test_guarded_index_distributes_store_under_complementary_guards() -> None:
    guard = atomic("selected", [])
    outcome = _store(
        fresh(DictValue, ()),
        GuardedValue(guard, StringValue("left"), StringValue("right")),
        TermValue(7),
    )

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 2
    assert all(isinstance(face, Completed) for face in outcome.exits)
    assert {face.guard for face in outcome.exits} == {guard, not_(guard)}
    assert {
        tuple(sorted(_entry_map(face.value).items())) for face in outcome.exits
    } == {(("left", 7),), (("right", 7),)}


def test_guarded_value_distributes_without_choosing_one_face() -> None:
    guard = atomic("selected", [])
    outcome = _store(
        fresh(DictValue, ()),
        StringValue("member"),
        GuardedValue(guard, TermValue(1), TermValue(2)),
    )

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 2
    assert {face.guard for face in outcome.exits} == {guard, not_(guard)}
    assert {_entry_map(face.value)["member"] for face in outcome.exits} == {1, 2}


def test_guarded_index_never_mints_a_runtime_store_effect() -> None:
    guard = atomic("selected", [])
    outcome = _store(
        fresh(DictValue, ()),
        GuardedValue(guard, StringValue("left"), StringValue("right")),
        TermValue(7),
    )

    assert all(isinstance(face, Completed) for face in outcome.exits)
