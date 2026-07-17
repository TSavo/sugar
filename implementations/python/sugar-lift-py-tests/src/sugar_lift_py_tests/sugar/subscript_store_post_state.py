from __future__ import annotations

from sugar_lift_py_tests.effect import (
    SubscriptStoreRuntimeEffect,
    runtime_effect_evidence,
)
from sugar_lift_py_tests.floor import ScopeRebind
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome


def cite_subscript_post_state(
    *,
    receiver_coordinate: str | None,
    receiver,
    updated,
    operation: str,
    site,
) -> Outcome:
    """Cite a structural receiver or witness a genuinely runtime selection."""
    if receiver_coordinate is not None:
        return Complete(ScopeRebind(receiver_coordinate, updated))
    return Incomplete(
        SubscriptStoreRuntimeEffect(
            "subscript store completed on a runtime-selected receiver whose "
            f"post-state has no structural coordinate; site={site}",
            **runtime_effect_evidence(operation, receiver, site),
        )
    )
