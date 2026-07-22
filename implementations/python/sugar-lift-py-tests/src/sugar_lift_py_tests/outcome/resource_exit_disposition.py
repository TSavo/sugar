"""Typed exit disposition for resource ``with`` — not Python decision callbacks.

Authority lives only in:

- ``NeverSuppresses`` — membrane/contract: never consume body halt
- ``ExitSuppressionContract`` — source-proven named suppress set (or empty)
- ``RuntimeSelected`` — undecidable; leave open residual under the guard
- ``Suppresses(matcher)`` — membrane matcher (exact kind+name)

No free-floating exception-name helpers. Production must not select semantics
by ad-hoc name checks outside these types.
"""

from __future__ import annotations

from typing import Literal

Verdict = Literal["suppress", "restore", "open"]


def disposition_verdict(disposition: object, effect: object) -> Verdict:
    """Decide suppress / restore / open for a body halt after exit completed.

    Never invents True/False for runtime-selected faces.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        NeverSuppresses,
        RuntimeSelected,
        Suppresses,
    )
    from sugar_lift_py_tests.floor.call_site_value import ExitSuppressionContract

    if disposition is None or isinstance(disposition, RuntimeSelected):
        return "open"

    if isinstance(disposition, NeverSuppresses):
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
        "resource exit disposition must be NeverSuppresses, "
        "ExitSuppressionContract, RuntimeSelected, or Suppresses; "
        f"got {type(disposition).__name__}"
    )
