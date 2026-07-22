"""The one effect router shared by ``Try`` and ``With`` (issue #5994, step 2/3).

T's ruling (verbatim intent, restated as code): the router takes a reduced
block's contribution entries and a typed ``context_manager_contract.Contract``
and decides what the contract's arm does to those entries -- never a vendor
spelling, never a manufactured green.

Arms:

- ``Expects(matcher)`` -- an OBLIGATION. The emitted fact is the FOL equality
  ``eq(str_const(expected_name), observed_term)``, wrapped in an ``InvValue``:
    * a matching-kind ``Incomplete(RaiseEffect)`` present -> ground-true
      (``observed_term = str_const(raised_name)``); the effect is CONSUMED --
      it was evidence, now discharged.
    * body completed with NO unresolved call coordinates -> ground-false
      (``observed_term = str_const("py.effect.none")``) -- the lying twin:
      the expected effect is asserted absent.
    * body carries unresolved call coordinates (the halt may be hiding behind
      a dig) -> do NOT claim absence; emit an opaque obligation
      ``atomic("py.effect.expected", [str_const(name), ...])`` instead of the
      InvValue (honest red until composition resolves the dig).
    * a non-matching Incomplete(RaiseEffect) (wrong effect) -> emit the
      ground-false equality AND KEEP the Incomplete: the wrong effect must not
      disappear.
- ``Suppresses(matcher)`` -- permission. A matching Incomplete is consumed
  (removed, nothing stated). Absence is fine (no fact). A non-matching effect
  propagates untouched.
- ``NeverSuppresses`` -- entries pass through unchanged. The router asserts
  nothing; it exists so resource expansion can name its policy.
- ``RuntimeSelected`` -- the router REFUSES: a loud, named error. Reaching the
  router with a runtime-selected contract is a defect in the caller (it must
  have stayed loud before reaching the router), not a policy the router picks.
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.context_manager_contract import (
    Contract,
    EffectMatcher,
    Expects,
    NeverSuppresses,
    RuntimeSelected,
    Suppresses,
)
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.inv_value import InvValue
from sugar_lift_py_tests.ir import atomic, eq, str_const
from sugar_lift_py_tests.outcome.incomplete import Incomplete

_EFFECT_ABSENT_NAME = "py.effect.none"
_EFFECT_EXPECTED_OBLIGATION = "py.effect.expected"


class RuntimeSelectedReachedRouter(RuntimeError):
    """Raised when a ``RuntimeSelected`` contract reaches ``route``.

    A runtime-selected exit must remain loud before it ever reaches this
    router (the caller's job); arriving here with one is a defect, never a
    policy this router is entitled to guess at.
    """


@dataclass(frozen=True)
class RoutedOutcome:
    """What the router hands back to its caller (Try or With).

    ``entries`` is the surviving contribution tuple -- what the caller splices
    into its own ``BlockValue.statements`` (or equivalent). ``stated_facts``
    is the subset of ``entries`` that are freshly-minted ``InvValue`` facts
    the router added (already included in ``entries`` too, since the caller
    needs both "here is the full record" and "here is what I just asserted"
    views without re-scanning for identity).
    """

    entries: tuple
    stated_facts: tuple = ()


def _matching_incomplete_raise(entries: tuple, matcher: EffectMatcher):
    """Return the (index, Incomplete) of the first Incomplete(RaiseEffect)
    whose effect matches ``matcher`` by EXACT kind+name (pinned rule -- a
    subclass raise is the mismatch twin, never silently matched), or None."""
    if matcher.kind != "raise":
        return None
    for index, entry in enumerate(entries):
        if isinstance(entry, Incomplete) and isinstance(entry.effect, RaiseEffect):
            if entry.effect.exception_name == matcher.name:
                return index, entry
    return None


def _first_incomplete_raise(entries: tuple):
    """Any Incomplete(RaiseEffect) at all, matching or not (for the wrong-effect
    twin: some raise happened, just not the one that was expected)."""
    for index, entry in enumerate(entries):
        if isinstance(entry, Incomplete) and isinstance(entry.effect, RaiseEffect):
            return index, entry
    return None


def _has_unresolved_call_coordinates(entries: tuple) -> bool:
    """True when the entries carry a call coordinate that has not yet been
    reduced -- the halt this router is asked to classify may be hiding behind
    that dig, so absence of a matching effect is NOT yet a fact.

    A callsite is "unresolved" when a ``CallSiteValue`` rides among the entries
    directly, or is cited by an ``InvValue.operand_callsites`` -- the one
    documented shape the ruling names. Both are inspected by this single
    helper; no other code in this module walks entries for callsites."""
    for entry in entries:
        if isinstance(entry, CallSiteValue):
            return True
        if isinstance(entry, InvValue) and entry.operand_callsites:
            return True
    return False


def _route_expects(entries: tuple, matcher: EffectMatcher) -> RoutedOutcome:
    matching = _matching_incomplete_raise(entries, matcher)
    if matching is not None:
        index, incomplete = matching
        observed = str_const(incomplete.effect.exception_name)
        # The TYPE obligation: discharged (ground-true equality; the halt is
        # the evidence, consumed). Each PAYLOAD obligation (T's conjunction
        # ruling) is its own row with its own verdict: a MessagePattern stays
        # UNDISCHARGED -- an opaque py.effect.message_matches over the SAME
        # observed witness -- until the effect carries authenticated message
        # content. Never one aggregate boolean; the unobservable message
        # neither silences the type testimony nor pretends the pattern held.
        facts = [InvValue(eq(str_const(matcher.name), observed))]
        for obligation in matcher.payload_obligations:
            facts.append(
                InvValue(
                    atomic(
                        "py.effect.message_matches",
                        [observed, str_const(obligation.pattern)],
                    )
                )
            )
        remaining = entries[:index] + entries[index + 1 :]
        return RoutedOutcome(
            entries=(*remaining, *facts), stated_facts=tuple(facts)
        )

    wrong = _first_incomplete_raise(entries)
    if wrong is not None:
        _, incomplete = wrong
        # Wrong effect: the type obligation is REFUTED (ground-false equality)
        # and the Incomplete is NOT consumed -- F must not disappear. Payload
        # obligations are INAPPLICABLE (their witness is the matching halt,
        # which does not exist), never independently emitted or passed.
        fact = InvValue(eq(str_const(matcher.name), str_const(incomplete.effect.exception_name)))
        return RoutedOutcome(entries=(*entries, fact), stated_facts=(fact,))

    if _has_unresolved_call_coordinates(entries):
        # Honest red: a dig may still produce the expected effect. Do not
        # claim absence -- emit an opaque obligation carrying the WHOLE
        # conjunction (type name + any payload patterns), all undischarged.
        operands = [str_const(matcher.name)] + [
            str_const(o.pattern) for o in matcher.payload_obligations
        ]
        obligation = InvValue(atomic(_EFFECT_EXPECTED_OBLIGATION, operands))
        return RoutedOutcome(entries=(*entries, obligation), stated_facts=(obligation,))

    # Completion with no hiding coordinates: the required-effect obligation is
    # REFUTED (asserted absent, ground-false). Payload obligations are
    # inapplicable -- no effect witness exists -- not independently "passed".
    fact = InvValue(eq(str_const(matcher.name), str_const(_EFFECT_ABSENT_NAME)))
    return RoutedOutcome(entries=(*entries, fact), stated_facts=(fact,))


def _route_suppresses(entries: tuple, matcher: EffectMatcher) -> RoutedOutcome:
    matching = _matching_incomplete_raise(entries, matcher)
    if matching is None:
        # Absence is fine; non-matching effects (if any) propagate untouched.
        return RoutedOutcome(entries=entries)
    index, _incomplete = matching
    remaining = entries[:index] + entries[index + 1 :]
    return RoutedOutcome(entries=remaining)


def route(entries: tuple, contract: Contract) -> RoutedOutcome:
    """Route a reduced block's contribution ``entries`` per the typed
    ``contract``. See module docstring for the per-arm semantics ruling."""
    if isinstance(contract, Expects):
        return _route_expects(entries, contract.matcher)
    if isinstance(contract, Suppresses):
        return _route_suppresses(entries, contract.matcher)
    if isinstance(contract, NeverSuppresses):
        return RoutedOutcome(entries=entries)
    if isinstance(contract, RuntimeSelected):
        raise RuntimeSelectedReachedRouter(
            "effect_router.route reached with RuntimeSelected: the caller "
            "must keep a runtime-selected exit loud before routing, never "
            "let it arrive here for the router to guess a policy"
        )
    raise TypeError(f"unknown context-manager contract: {type(contract).__name__}")
