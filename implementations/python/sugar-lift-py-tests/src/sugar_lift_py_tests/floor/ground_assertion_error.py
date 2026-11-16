from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sugar_lift_py_tests.outcome import ExitSet


def ground_assertion_error(*, site) -> ExitSet:
    """Construct the exact exceptional exit from a proved-false assertion."""
    from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

    return ground_exceptional_exit(
        exception_name="AssertionError", site=site, owner="ground_assertion_error"
    )
