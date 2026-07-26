"""The panic tail, by (owner x value category).

Four laws, each with both faces and an exact cardinality:

``attribute`` x the constructed containers
    a dict/list/tuple/set literal owns no field the lift knows and its methods
    have no body here, so ``.name`` stays the ``py.getattr`` coordinate -- the
    same law ``StringValue`` and ``PredicateValue`` already state. The
    discriminating face: the coordinate carries the RECEIVER's own term, so two
    receivers do not collapse to one shape, and a value that still has no arm
    still panics.

``guarded`` x ``PredicateValue``
    a carried boolean is a value, not an exit and not an obligation, so it
    rides under a guard unchanged. The discriminating face: ``InvValue`` DOES
    weaken under a guard, because that is where the obligation lives.

``contains`` x a guarded needle
    a needle split by a guard is not one needle, so it distributes into its
    faces and rejoins under the same guard before the receiver's own law runs.
    The discriminating face: an unguarded needle still takes that law.

``rewrap_pending`` x two pending contract demands
    equal ``demand_cid`` is the SAME content-addressed obligation reached
    twice, and conjunction is idempotent. The discriminating face: two DISTINCT
    demands still panic, because carrying one would drop the other.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.floor import DictValue, SymbolicValue, TermValue
from sugar_lift_py_tests.floor.list_value import ListValue
from sugar_lift_py_tests.floor.predicate_value import PredicateValue
from sugar_lift_py_tests.floor.set_value import SetValue
from sugar_lift_py_tests.floor.tuple_value import TupleValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import atomic, implies
from sugar_lift_py_tests.outcome import Complete

# --------------------------------------------------------------------------
# attribute x the constructed containers
# --------------------------------------------------------------------------


def _container(kind):
    entries = (TermValue(1), TermValue(2))
    if kind is DictValue:
        return DictValue(((TermValue(1), TermValue(10)),))
    return kind(entries)


@pytest.mark.parametrize("kind", [DictValue, ListValue, TupleValue, SetValue])
def test_container_attribute_is_the_py_getattr_coordinate(kind) -> None:
    outcome = _container(kind).attribute("renamed_member", "site")
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, SymbolicValue)
    assert outcome.value.term.name == "py.getattr"


@pytest.mark.parametrize("kind", [DictValue, ListValue, TupleValue, SetValue])
def test_the_coordinate_names_the_attribute_that_was_asked_for(kind) -> None:
    """Not one shape for every name -- the name is an argument of the symbol."""
    first = _container(kind).attribute("renamed_alpha", "site").value.term
    second = _container(kind).attribute("renamed_beta", "site").value.term
    assert first != second


def test_the_coordinate_carries_the_receivers_own_term() -> None:
    """Two receivers of one attribute do not collapse into one coordinate."""
    short = ListValue((TermValue(1),)).attribute("renamed_member", "site").value.term
    long = (
        ListValue((TermValue(1), TermValue(2)))
        .attribute("renamed_member", "site")
        .value.term
    )
    assert short != long


def test_a_value_with_no_attribute_arm_stays_loud() -> None:
    """The discriminating face: this drained four categories, not the floor."""
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    class RenamedFieldlessValue(FloorValue):
        pass

    with pytest.raises(ConstructionPanic) as excinfo:
        RenamedFieldlessValue().attribute("renamed_member", "site")
    assert excinfo.value.info.owner == "attribute"
    assert excinfo.value.info.observed == "RenamedFieldlessValue"


# --------------------------------------------------------------------------
# guarded x PredicateValue
# --------------------------------------------------------------------------


def test_a_carried_predicate_rides_under_a_guard_unchanged() -> None:
    predicate = PredicateValue(atomic("renamed_choice", []), "site")
    assert predicate.guarded(atomic("renamed_guard", [])) is predicate


def test_the_guard_does_not_weaken_the_carried_formula() -> None:
    """`x = (a == b) if c else d` must not make x true wherever c is false."""
    carried = atomic("renamed_choice", [])
    guard = atomic("renamed_guard", [])
    assert PredicateValue(carried, "site").guarded(guard).formula == carried
    assert PredicateValue(carried, "site").guarded(guard).formula != implies(
        guard, carried
    )


def test_an_obligation_does_weaken_under_the_same_guard() -> None:
    """The discriminating face: an InvValue is where a guard IS an implication."""
    from sugar_lift_py_tests.floor.inv_value import InvValue

    carried = atomic("renamed_claim", [])
    guard = atomic("renamed_guard", [])
    guarded = InvValue(carried, "site").guarded(guard)
    assert guarded.formula == implies(guard, carried)


def test_a_value_with_no_guarded_arm_stays_loud() -> None:
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    class RenamedUnguardableValue(FloorValue):
        pass

    with pytest.raises(ConstructionPanic) as excinfo:
        RenamedUnguardableValue().guarded(atomic("renamed_guard", []))
    assert excinfo.value.info.owner == "guarded"
    assert excinfo.value.info.observed == "RenamedUnguardableValue"


# --------------------------------------------------------------------------
# two pending contract demands
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _RenamedDemand:
    demand_cid: str


def _pending(cid: str, value):
    from sugar_lift_py_tests.caller_parameter_contract import (
        ContractConditionalConstructionV1,
    )

    return ContractConditionalConstructionV1(
        source_node="renamed_module.py:1:0",
        candidate=atomic("renamed_candidate", []),
        candidate_cid=f"blake3-512:{cid}",
        demands=(_RenamedDemand(f"blake3-512:{cid}"),),
        value=value,
    )


def test_one_obligation_reached_twice_is_carried_once() -> None:
    """Idempotence: `demand_cid` is content, so the same obligation unions to one."""
    from sugar_lift_py_tests.floor.single_outcome_law import rewrap_pending

    result = rewrap_pending(
        _pending("aaaa", TermValue(1)),
        _pending("aaaa", TermValue(2)),
        owner="renamed_join",
        blame="renamed_module.py:1:0",
    )
    assert result.sole_demand().demand_cid == "blake3-512:aaaa"


def test_two_distinct_obligations_join_and_both_survive() -> None:
    """SUPERSEDED PANIC, NOW A LAW (#6352).

    This used to assert the loud refusal, because the carrier held exactly one
    demand and carrying one would DROP the other. The panic named its own
    replacement -- a demand SET -- and that landed. The assertion moves from
    "it refuses" to "BOTH obligations survive the join", which is the property
    the refusal was protecting.
    """
    from sugar_lift_py_tests.floor.single_outcome_law import rewrap_pending

    result = rewrap_pending(
        _pending("aaaa", TermValue(1)),
        _pending("bbbb", TermValue(2)),
        owner="renamed_join",
        blame="renamed_module.py:1:0",
    )
    assert {demand.demand_cid for demand in result.demands} == {
        "blake3-512:aaaa",
        "blake3-512:bbbb",
    }


def test_a_partition_still_has_nowhere_to_carry_a_demand() -> None:
    """The third face: not a second pending, so the exit-algebra gap stands."""
    from sugar_lift_py_tests.floor.single_outcome_law import rewrap_pending
    from sugar_lift_py_tests.outcome import ExitSet

    with pytest.raises(ConstructionPanic) as excinfo:
        rewrap_pending(
            _pending("aaaa", TermValue(1)),
            ExitSet(()),
            owner="renamed_join",
            blame="renamed_module.py:1:0",
        )
    assert "cannot share one carried value" in excinfo.value.info.observed


# --------------------------------------------------------------------------
# contains x a guarded needle
# --------------------------------------------------------------------------


def _guarded(when_true, when_false):
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue

    return GuardedValue(atomic("renamed_guard", []), when_true, when_false)


def test_a_guarded_string_needle_distributes_and_rejoins() -> None:
    from sugar_lift_py_tests.floor.string_value import StringValue

    outcome = StringValue("renamed_haystack").contains(
        _guarded(StringValue("renamed"), StringValue("absent_needle")), "site"
    )
    # One rejoined answer under the needle's own guard -- not a panic, and not
    # one arm silently chosen.
    assert isinstance(outcome, Complete)
    assert outcome.value is not None


@pytest.mark.parametrize("kind", [ListValue, TupleValue, SetValue])
def test_a_guarded_sequence_needle_distributes(kind) -> None:
    members = (TermValue(1), TermValue(2))
    outcome = kind(members).contains(_guarded(TermValue(1), TermValue(9)), "site")
    assert isinstance(outcome, Complete)


def test_a_guarded_dict_key_distributes() -> None:
    d = DictValue(((TermValue(1), TermValue(10)),))
    assert isinstance(
        d.contains(_guarded(TermValue(1), TermValue(9)), "site"), Complete
    )


def test_an_unguarded_needle_still_takes_the_receivers_own_law() -> None:
    """The discriminating face: distribution must not swallow the real law."""
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    hay = StringValue("renamed_haystack")
    assert isinstance(
        hay.contains(StringValue("renamed"), "site").value, TrueBoolLiteralSugar
    )
    assert isinstance(
        hay.contains(StringValue("no_such_part"), "site").value, FalseBoolLiteralSugar
    )
