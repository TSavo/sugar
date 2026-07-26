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

There are exactly two ways an arm can answer with something that is not one
value and not one effect, and they are different obligations, not one blob:

- A PENDING PARAMETER CONTRACT (`ContractConditionalConstructionV1`). The arm
  reduced to a value, but the value carries a demand the linker has not yet
  discharged -- e.g. `(a if c else b)[i]` where `b` is a formal, so the arm's
  subscript enrolled `python:indexable(b)`. This is not a gap: `pending_demand`
  hoists the demand out under the arm's own guard and hands the join the carried
  value, which is what the arm actually reduced to.

- A PARTITION (`ExitSet`). The arm's own operation split into completed and
  halted faces -- a store inside a conditional arm, a call that can halt. Fusing
  a partition back into one `GuardedValue` arm has no honest shape here: the halt
  face is not a value and the join has no seam to put it on. That is a real
  construction gap, and `require_single_value` panics with it NAMED, so it is
  loud and counted rather than an empty `AssertionError`.
"""

from __future__ import annotations

SINGLE_OUTCOME_LAW = (
    "an operation distributed into a guarded arm answers with exactly one "
    "outcome: one value (Complete) or one effect (Incomplete)"
)


def pending_demand(outcome, guard):
    """Hoist a pending parameter-contract demand off an arm's answer.

    Returns ``(pending_entry, value_outcome)``. ``pending_entry`` is ``None``
    unless the arm answered with a pending contract; when it is not ``None``, its
    demand has already been weakened to ``guard`` -- the caller owes the
    obligation only on the face the arm occupies -- and ``value_outcome`` is the
    plain ``Complete`` the join should consume.
    """
    from sugar_lift_py_tests.caller_parameter_contract import (
        ContractConditionalConstructionV1,
    )
    from sugar_lift_py_tests.outcome import Complete

    if not isinstance(outcome, ContractConditionalConstructionV1):
        return None, outcome
    return outcome.demanded_under(guard), Complete(outcome.value)


def rewrap_pending(pending, outcome, *, owner, blame):
    """Re-attach a hoisted demand to a joined result, or be loud.

    A joined ``Complete`` takes the demand back and the entry rides on into the
    block record. A joined partition or effect has nowhere to carry it: one entry
    holds exactly one value, so the demand would have to be dropped. Dropping a
    pending obligation silently would let a caller discharge nothing and still
    look resolved, so it panics NAMED instead.
    """
    from dataclasses import replace

    from sugar_lift_py_tests.outcome import Complete

    if pending is None:
        return outcome
    if isinstance(outcome, Complete):
        return replace(pending, value=outcome.value)
    from sugar_lift_py_tests.caller_parameter_contract import (
        ContractConditionalConstructionV1,
    )
    from sugar_lift_py_tests.gap.info import GapKind
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    # Two different next architectures, named apart rather than blurred: a second
    # PENDING entry wants the entry to carry a demand SET; a PARTITION wants the
    # exit algebra to have an arm for a pending demand at all.
    if isinstance(outcome, ContractConditionalConstructionV1):
        if outcome.demand.demand_cid == pending.demand.demand_cid:
            # NOT two demands. ``demand_cid`` is the content address of the
            # whole obligation -- owner source identity, formal coordinate,
            # operation site, demanded formula, candidate. Equal cids mean the
            # SAME obligation reached this join twice through a shared outcome
            # DAG (`p[0]` read once and consumed on both faces of a fold).
            #
            # Conjunction is idempotent: `F and F` IS `F`. The joined outcome
            # already carries that exact demand, so it rides on unchanged. This
            # discharges nothing, weakens nothing and invents nothing -- it is
            # the arithmetic of the obligation, not a fallback. Two DISTINCT
            # demands still need a demand SET and stay loud below.
            return outcome
        observed = (
            f"two distinct pending contract demands ({pending.demand.demand_cid} "
            f"and {outcome.demand.demand_cid}) joined onto one constructed value"
        )
        fix = (
            "widen ContractConditionalConstructionV1 to carry a demand SET; "
            "never drop the obligation"
        )
    else:
        observed = (
            f"a hoisted parameter contract demand ({pending.demand.demand_cid}) "
            f"joined onto a {type(outcome).__name__}, which carries no single value"
        )
        fix = (
            "give the exit algebra an arm for a pending contract demand so a "
            "partition can carry it; never drop the obligation"
        )
    construction_panic_gap(
        owner=owner,
        blame=blame,
        observed=observed,
        requested="one joined value that can carry every pending demand",
        fix=fix,
        gap_kind=GapKind.FLOOR,
    )


def require_single_value(outcome, *, owner, blame, arm: str):
    """The arm's answer as one value, or a NAMED construction gap.

    Callers must already have handled the ``Incomplete`` face (an effect IS one
    lawful outcome) and hoisted any pending demand through ``pending_demand``.
    What is left that is not ``Complete`` is a partition, and it is a gap.
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
