from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sugar_lift_py_tests.outcome import Outcome


def ground_exception_exit(*, exception_name: str, site) -> Outcome:
    """Construct an exceptional exit whose triggering operands are proved ground."""
    import hashlib
    from pathlib import Path

    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.gap.panic import factory_panic_gap
    from sugar_lift_py_tests.floor import ExceptionValue, RaiseValue
    from sugar_lift_py_tests.outcome import Complete

    if Path(site.filename).is_absolute():
        factory_panic_gap(
            owner="ground_exception_exit",
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
    exception = ExceptionValue(exception_name, (), site)
    return Complete(
        RaiseValue(
            RaiseEffect(exception_name, str(site), source_sha256),
            exception=exception,
        )
    )
