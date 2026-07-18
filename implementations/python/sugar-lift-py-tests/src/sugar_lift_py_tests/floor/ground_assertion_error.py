from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sugar_lift_py_tests.outcome import Outcome


def assertion_raise_effect(*, site):
    """Construct source-cited ``AssertionError`` testimony for one assert."""
    import hashlib
    from pathlib import Path

    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.factory import factory_panic_gap

    if Path(site.filename).is_absolute():
        factory_panic_gap(
            owner="ground_assertion_error",
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
    return RaiseEffect("AssertionError", str(site), source_sha256)


def ground_assertion_error(*, site) -> Outcome:
    """Construct the exact exceptional exit from a proved-false assertion."""
    from sugar_lift_py_tests.floor import ExceptionValue, RaiseValue
    from sugar_lift_py_tests.outcome import Complete

    exception = ExceptionValue("AssertionError", (), site)
    return Complete(
        RaiseValue(
            assertion_raise_effect(site=site),
            exception=exception,
        )
    )
