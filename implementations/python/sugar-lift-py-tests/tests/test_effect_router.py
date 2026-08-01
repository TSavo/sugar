"""Pure-unit tests for the shared effect router (issue #5994, step 2/3).

Entries are constructed directly -- no tree lifting. Every arm is exercised
both directions per T's ruling in context_manager_contract.py.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    EffectMatcher,
    Expects,
    NeverSuppresses,
    RuntimeSelected,
    Suppresses,
)
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.effect_router import (
    RoutedOutcome,
    RuntimeSelectedReachedRouter,
    route,
)
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.inv_value import InvValue
from sugar_lift_py_tests.ir import atomic, eq, make_var, str_const
from sugar_lift_py_tests.outcome.incomplete import Incomplete
from sugar_lift_py_tests.effect.warning_effect import WarningEffect
from sugar_lift_py_tests.floor.warning_observation_value import WarningObservationValue


def _raise_incomplete(name: str) -> Incomplete:
    return Incomplete(RaiseEffect.for_builtin(name, occurrence='implementations/python/sugar-lift-py-tests/tests/test_effect_router.py:33:0'))


def _some_fact() -> InvValue:
    return InvValue(atomic("py.truthy", [make_var("x")]))


def _callsite(name: str = "f") -> CallSiteValue:
    return CallSiteValue(
        target_name=name,
        arg_values=(),
        parameters=(),
        term=make_var(f"__callsite_{name}"),
        body=None,
    )


def _warning(name: str, message: str | None = None) -> WarningObservationValue:
    return WarningObservationValue(WarningEffect(name, message=message))


# --- Expects -----------------------------------------------------------


def test_expects_matching_raise_ground_true_and_consumes_effect():
    incomplete = _raise_incomplete("ValueError")
    other = _some_fact()
    outcome = route(
        (other, incomplete), Expects(EffectMatcher(kind="raise", name="ValueError"))
    )
    assert isinstance(outcome, RoutedOutcome)
    assert incomplete not in outcome.entries
    assert other in outcome.entries
    fact = outcome.stated_facts[0]
    assert isinstance(fact, InvValue)
    assert fact.formula == eq(str_const("ValueError"), str_const("ValueError"))


def test_expects_completion_no_coordinates_ground_false_lying_twin():
    other = _some_fact()
    outcome = route((other,), Expects(EffectMatcher(kind="raise", name="ValueError")))
    assert other in outcome.entries
    fact = outcome.stated_facts[0]
    assert fact.formula == eq(str_const("ValueError"), str_const("py.effect.none"))


def test_expects_wrong_effect_ground_false_and_incomplete_survives():
    incomplete = _raise_incomplete("KeyError")
    outcome = route(
        (incomplete,), Expects(EffectMatcher(kind="raise", name="ValueError"))
    )
    assert incomplete in outcome.entries  # F must not disappear
    fact = outcome.stated_facts[0]
    assert fact.formula == eq(str_const("ValueError"), str_const("KeyError"))


def test_expects_unresolved_callsite_value_emits_opaque_obligation_no_absence_claim():
    site = _callsite()
    outcome = route((site,), Expects(EffectMatcher(kind="raise", name="ValueError")))
    # The obligation IS a stated inv row (an InvValue -- a raw formula would
    # crash the record); what is NOT stated is ABSENCE: the fact is the opaque
    # py.effect.expected, never the ground-false equality.
    assert len(outcome.stated_facts) == 1
    assert outcome.stated_facts[0].formula == atomic(
        "py.effect.expected", [str_const("ValueError")]
    )
    assert site in outcome.entries
    obligation = [e for e in outcome.entries if e is not site]
    assert len(obligation) == 1
    assert obligation[0].formula == atomic(
        "py.effect.expected", [str_const("ValueError")]
    )


def test_expects_unresolved_operand_callsites_on_inv_also_defers():
    site = _callsite()
    inv_with_callsite = InvValue(
        atomic("py.truthy", [make_var("y")]), operand_callsites=(site,)
    )
    outcome = route(
        (inv_with_callsite,), Expects(EffectMatcher(kind="raise", name="ValueError"))
    )
    assert len(outcome.stated_facts) == 1
    assert outcome.stated_facts[0].formula.name == "py.effect.expected"
    assert inv_with_callsite in outcome.entries


def test_expects_matching_warning_consumes_non_halting_observation():
    warning = _warning("FutureWarning")
    outcome = route(
        (warning,), Expects(EffectMatcher(kind="warning", name="FutureWarning"))
    )
    assert warning not in outcome.entries
    assert outcome.stated_facts[0].formula == eq(
        str_const("FutureWarning"), str_const("FutureWarning")
    )


def test_expects_wrong_warning_refutes_and_preserves_observation():
    warning = _warning("UserWarning")
    outcome = route(
        (warning,), Expects(EffectMatcher(kind="warning", name="FutureWarning"))
    )
    assert warning in outcome.entries
    assert outcome.stated_facts[0].formula == eq(
        str_const("FutureWarning"), str_const("UserWarning")
    )


# --- Suppresses ----------------------------------------------------------


def test_suppresses_matching_consumed_silently():
    incomplete = _raise_incomplete("ValueError")
    outcome = route(
        (incomplete,), Suppresses(EffectMatcher(kind="raise", name="ValueError"))
    )
    assert outcome.entries == ()
    assert outcome.stated_facts == ()


def test_suppresses_absence_nothing_happens():
    other = _some_fact()
    outcome = route(
        (other,), Suppresses(EffectMatcher(kind="raise", name="ValueError"))
    )
    assert outcome.entries == (other,)
    assert outcome.stated_facts == ()


def test_suppresses_non_match_propagates_untouched():
    incomplete = _raise_incomplete("KeyError")
    outcome = route(
        (incomplete,), Suppresses(EffectMatcher(kind="raise", name="ValueError"))
    )
    assert outcome.entries == (incomplete,)
    assert outcome.stated_facts == ()


# --- NeverSuppresses -------------------------------------------------------


def test_never_suppresses_identity_with_effect_present():
    incomplete = _raise_incomplete("ValueError")
    outcome = route((incomplete,), NeverSuppresses())
    assert outcome.entries == (incomplete,)
    assert outcome.stated_facts == ()


def test_never_suppresses_identity_without_effect():
    other = _some_fact()
    outcome = route((other,), NeverSuppresses())
    assert outcome.entries == (other,)
    assert outcome.stated_facts == ()


# --- RuntimeSelected -------------------------------------------------------


def test_runtime_selected_refuses_loudly():
    with pytest.raises(RuntimeSelectedReachedRouter):
        route((_raise_incomplete("ValueError"),), RuntimeSelected())


def test_runtime_selected_refuses_loudly_empty_entries_too():
    with pytest.raises(RuntimeSelectedReachedRouter):
        route((), RuntimeSelected())
