from __future__ import annotations

from sugar_lift_py_tests.floor import FloorValue

from .complete import Complete
from .incomplete import Incomplete
from .outcome import Outcome


def complete_value(outcome: Outcome, *, owner: str) -> FloorValue:
    """Project a single completed floor value, or refuse loudly.

    After store ExitSet composition (#6246), a body may reduce to multi-arm
    ``ExitSet`` rather than ``Complete``. Reading ``.value`` on that is a bare
    ``AttributeError`` — permanent-floor red. Refuse as a typed construction
    gap so kit-domain multi-arm outcomes stay on the typed-gap axis, never bare.
    """
    if isinstance(outcome, Incomplete):
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner=owner,
            blame=owner,
            observed=f"Incomplete effect (reason={outcome.reason!r}); no completed floor value",
            requested="Complete floor value",
            fix="do not project complete_value from Incomplete; reduce or leave the gap loud",
        )
    if isinstance(outcome, Complete):
        return outcome.value
    from .exit_set import ExitSet

    if isinstance(outcome, ExitSet):
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
        from sugar_lift_py_tests.gap.panic import construction_panic

        construction_panic(
            ConstructionGap(
                owner=owner,
                blame=owner,
                observed=f"ExitSet with {len(outcome.exits)} arms",
                requested="one Complete floor value",
                fix=(
                    "multi-arm store/control outcomes cannot force_floor to a single "
                    "value; leave the projection absent or reduce under ExitSet routing"
                ),
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.PROJECTION,
            )
        )
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner=owner,
        blame=owner,
        observed=f"outcome species {type(outcome).__name__} has no complete_value arm",
        requested="Complete | ExitSet (ExitSet already handled) | Incomplete (refused)",
        fix=f"write complete_value arm for {type(outcome).__name__} or refuse earlier",
    )
