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
    from sugar_lift_py_tests.gap.panic import construction_panic_gap
    from sugar_lift_py_tests.floor import ExceptionValue, RaiseValue
    from sugar_lift_py_tests.outcome import Complete

    del owner, operation, index, length
    filename = (
        getattr(site, "filename", None) or getattr(site, "path", None) or str(site)
    )
    if Path(filename).is_absolute():
        construction_panic_gap(
            owner="ground_index_error",
            blame=site,
            observed="absolute source locus",
            requested="workspace-relative source locus",
            fix="route the source through the workspace-relative lift door",
        )
    # ConstructionSite-like handles expose ``source``; SourceFragment exposes
    # the pinned file text on ``unit.source`` (``.text`` is the span slice).
    source_text = getattr(site, "source", None)
    if source_text is None:
        unit = getattr(site, "unit", None)
        source_text = getattr(unit, "source", None) if unit is not None else None
    source_sha256 = (
        hashlib.sha256(source_text.encode()).hexdigest()
        if isinstance(source_text, str)
        else None
    )
    exception = ExceptionValue("IndexError", (), site)
    return Complete(
        RaiseValue(
            RaiseEffect("IndexError", str(site), source_sha256),
            exception=exception,
        )
    )
