from __future__ import annotations

from typing import NoReturn


def ground_index_error(
    *,
    owner: str,
    operation: str,
    index: int,
    length: int,
    site,
) -> NoReturn:
    """Keep a decidable IndexError loud until exceptional exits are constructed."""
    from sugar_lift_py_tests.factory import factory_panic_gap

    factory_panic_gap(
        owner=owner,
        blame=site,
        observed=f"{operation} index={index} length={length}",
        requested="constructed Python IndexError exit",
        fix=(
            "construct the exact IndexError exceptional exit; a concrete "
            "out-of-range index cannot mint RuntimeEffect authority"
        ),
    )
