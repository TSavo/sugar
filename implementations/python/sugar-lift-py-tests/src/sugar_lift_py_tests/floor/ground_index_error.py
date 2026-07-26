from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sugar_lift_py_tests.outcome import Outcome


def ground_index_error(
    *,
    owner: str,
    operation: str,
    index: int,
    length: int,
    site,
) -> Outcome:
    """Construct the exact exceptional exit from a proved-failing bounds check."""
    from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

    del owner, operation, index, length
    return ground_exceptional_exit(
        exception_name="IndexError", site=site, owner="ground_index_error"
    )
