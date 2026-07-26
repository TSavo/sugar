"""Typed exit disposition: ONE contract decides BOTH edges of a body exit.

A body ``ExitSet`` face has exactly two shapes: it **completed** carrying a
value, or it **halted** carrying an effect and its pre-halt state. An exit
contract is the authority on what the enclosing block does with each shape,
and both are decided here, by one call. There is no edge the algebra answers
on its own.

Authority lives only in typed contracts:

- ``NeverSuppresses`` — never consume a body halt; a completion completes
- ``ExitSuppressionContract`` — source-proven named suppress set (or empty)
- ``RuntimeSelected`` — undecidable; leave the halt open under its guard
- ``Suppresses(matcher)`` — membrane matcher (exact kind+name)
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
            owner="EffectBoundaryDisposition",
            observed="matching raise face omitted its pre-effect state",
            requested="ExitSet Halted face carrying the real pre-halt state",
            fix="repair the block reducer; never fabricate a continuation state",
        )
    if isinstance(verdict, MatchDecided):
        return None
    if isinstance(verdict, MatchRetained):
        # The identity matched; only the message predicate is open. Under it
        # the boundary consumes, under its complement the ORIGINAL halt stands.
        return RetainedObligation(
            obligation=verdict.obligation, held=None, failed=incoming.effect
        )
    raise TypeError(
        "message verdict must be MatchDecided or MatchRetained; "
        f"got {type(verdict).__name__}"
    )


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

    if disposition is None or isinstance(disposition, RuntimeSelected):
        return "open"

    if isinstance(disposition, (NeverSuppresses, NeverSuppressesDispositionV1)):
        return "restore"

    if isinstance(disposition, ExitSuppressionContract):
        name = getattr(effect, "exception_name", None)
        if not isinstance(name, str) or not name:
            return "open"
        return "suppress" if disposition.suppresses_exception(name) else "restore"

    if isinstance(disposition, Suppresses):
        matcher = disposition.matcher
        if getattr(matcher, "kind", None) != "raise":
            return "open"
        name = getattr(effect, "exception_name", None)
        if name == matcher.name:
            return "suppress"
        return "restore"

    raise TypeError(
        "exit disposition must be NeverSuppresses, ExitSuppressionContract, "
        "RuntimeSelected, Suppresses, or EffectBoundaryDisposition; "
        f"got {type(disposition).__name__}"
    )
