from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sugar_lift_py_tests.outcome import Outcome


def ground_exception_exit(*, exception_name: str, site) -> Outcome:
    """Construct an exceptional exit whose triggering operands are proved ground."""
    from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

    return ground_exceptional_exit(
        exception_name=exception_name, site=site, owner="ground_exception_exit"
    )
