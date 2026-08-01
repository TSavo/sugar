"""Typed exit disposition: ONE contract decides BOTH edges of a body exit.

A body ``ExitSet`` face has exactly two shapes: it **completed** carrying a
value, or it **halted** carrying an effect and its pre-halt state. An exit
contract is the authority on what the enclosing block does with each shape,
and both are decided here, by one call. There is no edge the algebra answers
on its own.

Authority lives only in typed contracts:

- ``NeverSuppresses`` — never consume a body halt; a completion completes
- ``ExitSuppressionContract`` — source-proven type-coordinate suppress set (or empty)
- ``RuntimeSelected`` — undecidable; leave the halt open under its guard
- ``Suppresses(matcher)`` — membrane matcher (raise + authenticated type)
- ``EffectBoundaryDisposition`` — assertion boundary; the only contract that
  can name an effect on the **completed** edge

No free-floating exception-name helpers. Production must not select semantics
by ad-hoc name checks outside these types.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetainedObligation:
    """A verdict this compiler cannot settle, kept as an explicit FOL partition.

    Returned instead of an effect when the contract's predicate is real but
    undecidable at lift. ``obligation`` is the predicate; ``held`` is the
    verdict under it and ``failed`` the verdict under its complement, each in
    the same codomain as an ordinary verdict (an ``Effect`` to halt with, or
    ``None`` to complete).

    This is the only shape that lets a router honour "never admitted, never
    dropped": the incoming exit leaves as two exits under complementary
    guards, so both faces reach the emitted FOL and neither was decided by
    silence.
    """

    obligation: object
    held: object
    failed: object


@dataclass(frozen=True)
class ConsumedObservation:
    """The boundary consumed this halt AND authenticated its observation slot.

    ``None`` already means "consumed"; this says the same thing and carries the
    testimony that authenticates the ``as`` slot. The facts are built from the
    ROUTED occurrence -- the exact effect this boundary matched -- so the slot
    is authenticated by the thing that actually happened and never by an
    ``E()`` the router invented. It is a separate shape rather than a flag
    because a consumed-without-binding face must remain unable to carry
    testimony at all.
    """

    facts: tuple


def exit_disposition_effect(disposition: object, incoming: object):
    """The verdict for one body exit: an ``Effect``, ``None``, or a retention.

    ``incoming`` is one body exit — ``Completed`` or ``Halted``. The outgoing
    exit always carries the incoming exit's state; the *only* thing a contract
    decides is whether that state leaves as a completion or as a halt, and with
    which effect. Returning ``incoming.effect`` therefore restores, returning
    ``None`` consumes, and returning a fresh effect is the boundary halting on
    its own behalf. A ``RetainedObligation`` says the contract's predicate did
    not settle and hands the router both faces plus the predicate.

    Never invents True/False for runtime-selected faces.
    """
    from sugar_lift_py_tests.context_manager_contract import EffectBoundaryDisposition
    from sugar_lift_py_tests.outcome.exit_set import Completed

    if isinstance(disposition, EffectBoundaryDisposition):
        if isinstance(incoming, Completed):
            # The boundary's own verdict on a body that never raised.
            return disposition.unmet
        return _boundary_halted_edge(disposition, incoming)

    if isinstance(incoming, Completed):
        # Every resource contract leaves a completion completed — but it must
        # still be a typed contract, so authenticate it on this edge too.
        _authenticate(disposition)
        return None

    verdict = _resource_verdict(disposition, incoming.effect)
    return None if verdict == "suppress" else incoming.effect


def _boundary_halted_edge(disposition, incoming):
    """Consume the halt this boundary was written to observe; restore the rest."""
    from sugar_lift_py_tests.authenticated_exception_matching import (
        MatchDecided,
        MatchRetained,
        raise_effect_message_verdict,
    )
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_source_tree.panic import SugarNotWritten

    matcher = disposition.matcher
    if not isinstance(incoming.effect, RaiseEffect):
        return incoming.effect
    verdict = raise_effect_message_verdict(
        incoming.effect, matcher.expected, matcher.message_pattern
    )
    if isinstance(verdict, MatchDecided) and not verdict.value:
        return incoming.effect
    # Consuming this halt means the boundary claims the body reached the raise
    # and stopped there, so the pre-halt state is load-bearing on BOTH the
    # settled and the retained face. Demand it before either.
    if incoming.state is None:
        raise SugarNotWritten(
            blame=incoming.effect.occurrence_id,
            owner="EffectBoundaryDisposition",
            observed="matching raise face omitted its pre-effect state",
            requested="ExitSet Halted face carrying the real pre-halt state",
            fix="repair the block reducer; never fabricate a continuation state",
        )
    if isinstance(verdict, MatchDecided):
        return _consumed(disposition, incoming)
    if isinstance(verdict, MatchRetained):
        # Some conjunct of the boundary's predicate is open -- the identity
        # test, the message test, or both conjoined. Under the obligation the
        # boundary consumes, under its complement the ORIGINAL halt stands.
        # Which conjunct is open is not this edge's business: the verdict is
        # one predicate and it is routed as one.
        return RetainedObligation(
            obligation=verdict.obligation,
            held=_consumed(disposition, incoming),
            failed=incoming.effect,
        )
    raise TypeError(
        "message verdict must be MatchDecided or MatchRetained; "
        f"got {type(verdict).__name__}"
    )


def _consumed(disposition, incoming):
    """Consume, carrying observation testimony only when a slot was declared.

    No slot -> plain ``None``. A declared slot is authenticated from
    ``incoming.effect``, the occurrence the matcher just decided on.
    """
    from sugar_lift_py_tests.effect_router import EffectBinding

    slot_id = getattr(disposition, "observation_slot_id", None)
    if slot_id is None:
        return None
    binding = EffectBinding(
        slot_id=slot_id,
        kind="raise",
        type_name=getattr(incoming.effect, "exception_name", None),
        effect=incoming.effect,
    )
    return ConsumedObservation(binding.to_facts(site=getattr(incoming, "site", None)))


def _authenticate(disposition: object) -> None:
    """Refuse an untyped disposition wherever it first reaches the algebra."""
    _resource_verdict(disposition, None)


def _resource_verdict(disposition: object, effect: object) -> str:
    """Decide suppress / restore / open for a body halt after the exit completed."""
    from sugar_lift_py_tests.context_manager_contract import (
        NeverSuppresses,
        NeverSuppressesDispositionV1,
        RuntimeSelected,
        Suppresses,
    )
    from sugar_lift_py_tests.floor.call_site_value import ExitSuppressionContract

    if isinstance(disposition, RuntimeSelected):
        return "open"

    if isinstance(disposition, (NeverSuppresses, NeverSuppressesDispositionV1)):
        return "restore"

    if isinstance(disposition, ExitSuppressionContract):
        return _exit_suppression_contract_verdict(disposition, effect)

    if isinstance(disposition, Suppresses):
        return _suppresses_verdict(disposition, effect)

    raise TypeError(
        "exit disposition must be NeverSuppresses, ExitSuppressionContract, "
        "RuntimeSelected, Suppresses, or EffectBoundaryDisposition; "
        f"got {type(disposition).__name__}"
    )


def _require_exception_type_coordinate(effect, *, owner: str):
    """Shared door: halt faces suppress only with an authenticated type coordinate."""
    from sugar_source_tree.panic import SugarNotWritten

    if effect is None:
        return None
    coordinate = getattr(effect, "exception_type_coordinate", None)
    if coordinate is None:
        raise SugarNotWritten(
            blame=getattr(effect, "occurrence_id", None) or owner,
            owner=owner,
            observed="effect without exception_type_coordinate",
            requested="authenticated exception_type_coordinate on the halt",
            fix=(
                "mint the raise through the ground exit door or an authenticated "
                "producer; do not suppress by exception_name spelling"
            ),
        )
    return coordinate


def _exit_suppression_contract_verdict(disposition, effect) -> str:
    """Suppress by coordinate membership only — never by exception_name spelling.

    LAW OF ONE with the Suppresses arm: both doors demand
    ``exception_type_coordinate``. Soft ``open`` on a missing name was the
    residual second mechanism after sin-cluster-5 Suppresses was fixed.
    """
    owner = "exit_disposition.ExitSuppressionContract"
    if effect is None:
        return "restore"
    coordinate = _require_exception_type_coordinate(effect, owner=owner)
    if not disposition.exception_type_coordinates:
        return "restore"
    return (
        "suppress"
        if disposition.suppresses_coordinate(coordinate)
        else "restore"
    )


def _suppresses_verdict(disposition, effect) -> str:
    """Suppress only by authenticated exception type coordinate, never by name.

    A name-less matcher and a name-less effect used to compare equal and
    suppress. Spelling is half-writing the match. Both this arm and
    ``ExitSuppressionContract`` demand ``exception_type_coordinate``; missing
    coordinate or name-less matcher is unwritten work (throw), not a soft open.
    """
    from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity
    from sugar_source_tree.panic import SugarNotWritten

    matcher = disposition.matcher
    if getattr(matcher, "kind", None) != "raise":
        return "open"
    owner = "exit_disposition.Suppresses"
    blame = getattr(effect, "occurrence_id", None) or owner
    matcher_name = getattr(matcher, "name", None)
    if not isinstance(matcher_name, str) or not matcher_name:
        raise SugarNotWritten(
            blame=blame,
            owner=owner,
            observed="name-less Suppresses matcher",
            requested="matcher carrying an exception type name with a builtin identity",
            fix=(
                "construct Suppresses with a real exception type; never let "
                "None == None suppress a coordinate-authenticated effect"
            ),
        )
    if effect is None:
        return "restore"
    coordinate = _require_exception_type_coordinate(effect, owner=owner)
    matcher_identity, _ = _builtin_exception_identity(matcher_name)
    if matcher_identity is None:
        raise SugarNotWritten(
            blame=blame,
            owner=owner,
            observed=f"matcher name {matcher_name!r} has no builtin type coordinate",
            requested="a language-owned exception type with python:exception_type_identity",
            fix="use a builtin exception type or an AuthenticatedRaiseMatcher coordinate path",
        )
    return "suppress" if coordinate == matcher_identity else "restore"
