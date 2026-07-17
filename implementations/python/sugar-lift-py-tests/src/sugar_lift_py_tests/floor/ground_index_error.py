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
    import hashlib
    from pathlib import Path

    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.factory import factory_panic_gap
    from sugar_lift_py_tests.floor import ExceptionValue, RaiseValue
    from sugar_lift_py_tests.outcome import Complete

    del owner, operation, index, length
    if Path(site.filename).is_absolute():
        factory_panic_gap(
            owner="ground_index_error",
            blame=site,
            observed="absolute source locus",
            requested="workspace-relative source locus",
            fix="route the source through the workspace-relative lift door",
        )
    source_sha256 = (
        hashlib.sha256(site.source.encode()).hexdigest()
        if site.source is not None
        else None
    )
    exception = ExceptionValue("IndexError", (), site)
    return Complete(
        RaiseValue(
            RaiseEffect("IndexError", str(site), source_sha256),
            exception=exception,
        )
    )
