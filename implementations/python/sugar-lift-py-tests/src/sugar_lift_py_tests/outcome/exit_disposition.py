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


def exit_disposition_effect(disposition: object, incoming: object):
    """The effect the outgoing exit halts with, or None to complete.

    ``incoming`` is one body exit — ``Completed`` or ``Halted``. The outgoing
    exit always carries the incoming exit's state; the *only* thing a contract
    decides is whether that state leaves as a completion or as a halt, and with
    which effect. Returning ``incoming.effect`` therefore restores, returning
    ``None`` consumes, and returning a fresh effect is the boundary halting on
    its own behalf.

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
        matches_raise_effect_with_message,
    )
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_source_tree.panic import SugarNotWritten

    matcher = disposition.matcher
    if not isinstance(incoming.effect, RaiseEffect):
        return incoming.effect
    if not matches_raise_effect_with_message(
        incoming.effect, matcher.expected, matcher.message_pattern
    ):
        return incoming.effect
    if incoming.state is None:
        raise SugarNotWritten(
            owner="EffectBoundaryDisposition",
            observed="matching raise face omitted its pre-effect state",
            requested="ExitSet Halted face carrying the real pre-halt state",
            fix="repair the block reducer; never fabricate a continuation state",
        )
    return None


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
