"""THE LAW: an operation distributed into a branch arm yields ONE outcome.

`GuardedValue._map` / `_predicate` and `PredicateValue`'s binding-join paths all
do the same thing: take one operation, apply it to each arm of a value that is
already split by a guard, and rejoin the per-arm answers under that guard. Every
one of them handled `Complete` and `Incomplete` and then wrote

    assert isinstance(true_outcome, Complete)

which is a bare assertion. A bare assert names no law: when it fired, the census
recorded `AssertionError: ` with an empty message, and there was nothing in the
failure to say what had been violated or what should replace it. Every assert in
that family is routed through this module instead, so the failure states the law.

An arm can answer with something that is not one value and not one effect in
one way: a PARTITION (`ExitSet`). The arm's own operation split into completed
and halted faces -- a store inside a conditional arm, a call that can halt.
Fusing a partition back into one `GuardedValue` arm has no honest shape here:
the halt face is not a value and the join has no seam to put it on. That is a
real construction gap, and `require_single_value` panics with it NAMED, so it is
loud and counted rather than an empty `AssertionError`.
"""

from __future__ import annotations

SINGLE_OUTCOME_LAW = (
    "an operation distributed into a guarded arm answers with exactly one "
    "outcome: one value (Complete) or one effect (Incomplete)"
)


def require_single_value(outcome, *, owner, blame, arm: str):
    """The arm's answer as one value, or a NAMED construction gap.

    Callers must already have handled the ``Incomplete`` face (an effect IS one
    lawful outcome). What is left that is not ``Complete`` is a partition, and it
    is a gap.
    """
    from sugar_lift_py_tests.outcome import Complete

    if isinstance(outcome, Complete):
        return outcome
    from sugar_lift_py_tests.gap.info import GapKind
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner=owner,
        blame=blame,
        observed=(
            f"the {arm} arm answered with {type(outcome).__name__}, violating: "
            f"{SINGLE_OUTCOME_LAW}"
        ),
        requested=SINGLE_OUTCOME_LAW,
        fix=(
            "rejoin the arm's partition in the exit algebra before the guarded "
            "join, so each face keeps its own guard"
        ),
        gap_kind=GapKind.FLOOR,
    )
