"""Typed exit disposition for resource ``with`` — not Python decision callbacks.

Authority lives only in:

- ``NeverSuppresses`` — membrane/contract: never consume body halt
- ``ExitSuppressionContract`` — source-proven named suppress set (or empty)
- ``RuntimeSelected`` — undecidable; leave open residual under the guard
- ``Suppresses(matcher)`` — membrane matcher (exact kind+name)
- ``AuthenticatedRaiseDisposition`` — source-authenticated expected type/pattern

No free-floating exception-name helpers. Production must not select semantics
by ad-hoc name checks outside these types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Verdict = Literal["suppress", "restore", "open"]


@dataclass(frozen=True)
class AuthenticatedRaiseDisposition:
    """Consume only the raise selected by authenticated contract operands."""

    expected_type: object
    message_pattern: object | None = None


def disposition_verdict(disposition: object, effect: object) -> Verdict:
    """Decide suppress / restore / open for a body halt after exit completed.

    Never invents True/False for runtime-selected faces.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        NeverSuppresses,
        NeverSuppressesDispositionV1,
        RuntimeSelected,
        Suppresses,
    )
    from sugar_lift_py_tests.floor.call_site_value import ExitSuppressionContract

    if isinstance(disposition, AuthenticatedRaiseDisposition):
        return (
            "suppress"
            if _matches_authenticated_raise(disposition, effect)
            else "restore"
        )

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
        "exit disposition must be AuthenticatedRaiseDisposition, NeverSuppresses, "
        "ExitSuppressionContract, RuntimeSelected, or Suppresses; "
        f"got {type(disposition).__name__}"
    )


def _matches_authenticated_raise(
    disposition: AuthenticatedRaiseDisposition, effect: object
) -> bool:
    import re

    from sugar_lift_py_tests.authenticated_exception_matching import (
        matches_raise_effect,
    )
    from sugar_lift_py_tests.effect import RaiseEffect

    if not isinstance(effect, RaiseEffect):
        return False
    if not matches_raise_effect(effect, disposition.expected_type):
        return False
    if disposition.message_pattern is None:
        return True
    pattern_value = getattr(disposition.message_pattern, "value", None)
    args = getattr(effect.raised_value, "arg_values", ())
    message_value = getattr(args[0], "value", None) if args else None
    return (
        isinstance(pattern_value, str)
        and isinstance(message_value, str)
        and re.search(pattern_value, message_value) is not None
    )
