"""The one effect router shared by ``Try`` and ``With`` (issue #5994, step 2/3).

Match once. Emit obligations and optional EffectBinding testimony for a
preallocated effect slot. No ambient tables; no second matching authority.
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
from sugar_lift_py_tests.floor.warning_observation_value import WarningObservationValue
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.inv_value import InvValue
from sugar_lift_py_tests.ir import atomic, ctor, eq, str_const
from sugar_lift_py_tests.outcome.incomplete import Incomplete

_EFFECT_ABSENT_NAME = "py.effect.none"
_EFFECT_EXPECTED_OBLIGATION = "py.effect.expected"


class RuntimeSelectedReachedRouter(RuntimeError):
    """Raised when a ``RuntimeSelected`` contract reaches ``route``."""


@dataclass(frozen=True)
class EffectBinding:
    """Explicit constructed testimony: slot S is authenticated by this effect.

    Part of the same record as other facts — not ambient memory, not embedded
    inside an EffectCoordinate floor value.
    """

    slot_id: str
    kind: str
    type_name: str | None
    effect: object  # RaiseEffect | WarningEffect | ...

    def to_facts(self, site=None) -> tuple:
        """FOL rows authenticating the slot.

        The **witness identity is the slot itself** (effect-slot(S) on returns).
        Type is separate testimony. Origin links the slot to a deterministic
        raise-effect occurrence when available — never identity-from-type-alone.
        """
        slot = str_const(self.slot_id)
        facts = [
            InvValue(
                eq(atomic("effect_slot_kind", [slot]), str_const(self.kind)),
                site=site,
            ),
        ]
        if self.type_name is not None:
            facts.append(
                InvValue(
                    eq(
                        atomic("effect_slot_type", [slot]),
                        str_const(self.type_name),
                    ),
                    site=site,
                )
            )
        # Origin: relationship to the originating halt occurrence, if known.
        occurrence = getattr(self.effect, "occurrence_id", None)
        if isinstance(occurrence, str) and occurrence:
            facts.append(
                InvValue(
                    eq(
                        atomic("effect_slot_origin", [slot]),
                        ctor(
                            "python:raise_effect_occurrence",
                            [str_const(occurrence)],
                        ),
                    ),
                    site=site,
                )
            )
        return tuple(facts)


@dataclass(frozen=True)
class RoutedOutcome:
    """Router result: surviving entries, stated obligation facts, slot bindings."""

    entries: tuple
    stated_facts: tuple = ()
    bindings: tuple = ()  # EffectBinding, ...


def _observed_effect(entry):
    if isinstance(entry, Incomplete) and isinstance(entry.effect, RaiseEffect):
        return "raise", entry.effect.exception_name, None, entry.effect
    if isinstance(entry, WarningObservationValue):
        return (
            "warning",
            entry.effect.category_name,
            entry.effect.message,
            entry.effect,
        )
    return None


def _matching_effect(entries: tuple, matcher: EffectMatcher):
    """First exact kind+name match, or None. Single match authority for route."""
    for index, entry in enumerate(entries):
        observed = _observed_effect(entry)
        if (
            observed is not None
            and observed[0] == matcher.kind
            and observed[1] == matcher.name
        ):
            return index, entry, observed
    return None


def _first_effect_of_kind(entries: tuple, kind: str):
    for index, entry in enumerate(entries):
        observed = _observed_effect(entry)
        if observed is not None and observed[0] == kind:
            return index, entry, observed
    return None


def _has_unresolved_call_coordinates(entries: tuple) -> bool:
    for entry in entries:
        if isinstance(entry, CallSiteValue):
            return True
        if isinstance(entry, InvValue) and entry.operand_callsites:
            return True
    return False


def _binding_for_slot(slot_id: str | None, observed) -> tuple:
    if slot_id is None or observed is None:
        return ()
    kind, type_name, _message, effect = observed
    return (
        EffectBinding(
            slot_id=slot_id,
            kind=kind,
            type_name=type_name,
            effect=effect,
        ),
    )


def _route_expects(
    entries: tuple,
    matcher: EffectMatcher,
    *,
    slot_id: str | None = None,
    site=None,
) -> RoutedOutcome:
    matching = _matching_effect(entries, matcher)
    if matching is not None:
        index, _entry, observation = matching
        observed = str_const(observation[1])
        facts = [InvValue(eq(str_const(matcher.name), observed), site=site)]
        for obligation in matcher.payload_obligations:
            message = observation[2]
            message_term = observed if message is None else str_const(message)
            facts.append(
                InvValue(
                    atomic(
                        "py.effect.message_matches",
                        [message_term, str_const(obligation.pattern)],
                    ),
                    site=site,
                )
            )
        bindings = _binding_for_slot(slot_id, observation)
        binding_facts = tuple(f for b in bindings for f in b.to_facts(site=site))
        remaining = entries[:index] + entries[index + 1 :]
        all_facts = (*facts, *binding_facts)
        return RoutedOutcome(
            entries=(*remaining, *all_facts),
            stated_facts=all_facts,
            bindings=bindings,
        )

    wrong = _first_effect_of_kind(entries, matcher.kind)
    if wrong is not None:
        _, _entry, observation = wrong
        fact = InvValue(
            eq(str_const(matcher.name), str_const(observation[1])), site=site
        )
        # Wrong path: slot not authenticated (no binding).
        return RoutedOutcome(entries=(*entries, fact), stated_facts=(fact,))

    if _has_unresolved_call_coordinates(entries):
        operands = [str_const(matcher.name)] + [
            str_const(o.pattern) for o in matcher.payload_obligations
        ]
        obligation = InvValue(atomic(_EFFECT_EXPECTED_OBLIGATION, operands), site=site)
        return RoutedOutcome(entries=(*entries, obligation), stated_facts=(obligation,))

    fact = InvValue(
        eq(str_const(matcher.name), str_const(_EFFECT_ABSENT_NAME)), site=site
    )
    return RoutedOutcome(entries=(*entries, fact), stated_facts=(fact,))


def _route_suppresses(
    entries: tuple, matcher: EffectMatcher, *, slot_id: str | None = None, site=None
) -> RoutedOutcome:
    del site
    matching = _matching_effect(entries, matcher)
    if matching is None:
        return RoutedOutcome(entries=entries)
    index, _entry, observation = matching
    remaining = entries[:index] + entries[index + 1 :]
    # Suppresses consumes; as-binding is not a Suppresses surface (tree stays loud).
    del slot_id, observation
    return RoutedOutcome(entries=remaining)


def route(
    entries: tuple,
    contract: Contract,
    *,
    slot_id: str | None = None,
    site=None,
) -> RoutedOutcome:
    """Route once. Optional ``slot_id`` receives EffectBinding testimony on match."""
    if isinstance(contract, Expects):
        return _route_expects(entries, contract.matcher, slot_id=slot_id, site=site)
    if isinstance(contract, Suppresses):
        return _route_suppresses(entries, contract.matcher, slot_id=slot_id, site=site)
    if isinstance(contract, NeverSuppresses):
        return RoutedOutcome(entries=entries)
    if isinstance(contract, RuntimeSelected):
        raise RuntimeSelectedReachedRouter(
            "effect_router.route reached with RuntimeSelected: the caller "
            "must keep a runtime-selected exit loud before routing, never "
            "let it arrive here for the router to guess a policy"
        )
    raise TypeError(f"unknown context-manager contract: {type(contract).__name__}")


def route_except(
    entries: tuple,
    matcher: EffectMatcher | None,
    *,
    slot_id: str | None = None,
    site=None,
) -> RoutedOutcome | None:
    """Single match for one try-handler arm. None = this arm does not match.

    Bare except (matcher is None) matches any raise; typed arms use exact name.
    On match: consume halt, emit optional slot binding facts.
    """
    matching = (
        _first_effect_of_kind(entries, "raise")
        if matcher is None
        else _matching_effect(entries, matcher)
    )
    if matching is None:
        return None
    index, _entry, observation = matching
    remaining = entries[:index] + entries[index + 1 :]
    bindings = _binding_for_slot(slot_id, observation)
    binding_facts = tuple(f for b in bindings for f in b.to_facts(site=site))
    return RoutedOutcome(
        entries=(*remaining, *binding_facts),
        stated_facts=binding_facts,
        bindings=bindings,
    )
