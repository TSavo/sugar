from __future__ import annotations

from sugar_lift_py_tests.floor import FloorValue

from .exit_set import ExitSet


def complete_value(outcome: ExitSet, *, owner: str) -> FloorValue:
    """Project a single completed floor value, or refuse loudly.

    After store ExitSet composition (#6246), a body may reduce to a multi-arm
    ``ExitSet``. Reading one value off that is a bare ``AttributeError`` --
    permanent-floor red. Refuse as a typed construction gap so kit-domain
    multi-arm outcomes stay on the typed-gap axis, never bare.
    """
    if isinstance(outcome, ExitSet):
        # One unconditional completed arm that owes nothing; an owing arm
        # keeps its debt and is refused below.
        value = outcome.completed_value()
        if value is not None and not outcome.owed_items():
            return value
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
        from sugar_lift_py_tests.gap.panic import construction_panic

        construction_panic(
            ConstructionGap(
                owner=owner,
                blame=owner,
                observed=f"ExitSet with {len(outcome.exits)} arms",
                requested="one unconditional completed floor value",
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
        requested="ExitSet",
        fix=f"write complete_value arm for {type(outcome).__name__} or refuse earlier",
    )
