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

  A pending OBLIGATION meeting a partition is a different question and is no
  longer a gap: it asks where the demand is owed, not which value the join
  takes. Every face is downstream of the construction that incurred it, so
  `rewrap_pending` puts it on every face, weakened under that face's own guard.
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

    Four arms, each conserving the obligation somewhere it is honestly owed: a
    ``Complete`` takes it back; a second carrier unions demand SETS by content
    address; an ``Incomplete`` carries it beside the effect it was incurred
    before; an ``ExitSet`` puts it on every face, weakened under that face's own
    guard. Any other outcome kind stays LOUD -- dropping a pending obligation
    silently would let a caller discharge nothing and still look resolved.
    """
    from dataclasses import replace

    from sugar_lift_py_tests.caller_parameter_contract import (
        ContractConditionalConstructionV1,
        merge_demands,
    )
    from sugar_lift_py_tests.outcome import Complete, Incomplete

    if pending is None:
        return outcome

    # A VALUE takes the obligations back and rides on into the block record.
    if isinstance(outcome, Complete):
        return replace(pending, value=outcome.value)

    # A SECOND CARRIER: union the demand sets (#6352). `demand_cid` is the
    # content address of the whole obligation, so the union dedupes the same
    # obligation reaching this join twice through a shared outcome DAG (`p[0]`
    # read once, consumed on both faces of a fold) and keeps two DISTINCT
    # obligations distinct. Nothing is conjoined into a single demand: each
    # carries its own formal coordinate, and fusing them would attribute one
    # obligation to a formal that does not own it.
    if isinstance(outcome, ContractConditionalConstructionV1):
        return replace(
            outcome, demands=merge_demands(pending.demands, outcome.demands)
        )

    # AN EFFECT: the obligation was incurred BEFORE the effect, on the path that
    # reached it (`o.x = p[k]` evaluates `p[k]`, then the store answers). It is
    # owed, and `Incomplete` carries it to the block record the same way it
    # carries branch conditions. The carried VALUE is dropped here on purpose --
    # there is no value on this face -- but the obligation is not.
    if isinstance(outcome, Incomplete):
        return replace(
            outcome,
            pending_contracts=(*outcome.pending_contracts, pending),
        )

    # A PARTITION. Every face of the partition is downstream of this obligation:
    # the carried value was constructed, incurring the demand, and only THEN did
    # the following step split. So the demand is owed on EVERY face -- owing it
    # on one only would drop it on the others.
    #
    # It attaches AS INCURRED. Each arm's own `guard` states the face it is owed
    # on, and `guard -> D` is minted once, at the block boundary that enrols it
    # (`function_universe_sugar._enrol_exit_obligations`). Weakening per face
    # here instead would re-mint a `demand_cid` per arm, and since a re-minted
    # obligation is a different destination, the same obligation reaching this
    # join twice through a shared outcome DAG would stop deduping -- `F and F`
    # would stop being `F`.
    #
    # This was the last LOUD category here, and the panic it replaces asked for
    # precisely this arm. `Completed.pending_contracts` is it (`Halted` has had
    # its twin since #6352), so the request is answered rather than re-raised.
    from sugar_lift_py_tests.caller_parameter_contract import merge_pending
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted

    if isinstance(outcome, ExitSet):
        exits = []
        for exit_ in outcome.exits:
            owed = merge_pending(exit_.pending_contracts, (pending,))
            if isinstance(exit_, Completed):
                exits.append(
                    Completed(exit_.guard, exit_.value, exit_.faces, owed)
                )
            else:
                exits.append(
                    Halted(
                        exit_.guard, exit_.effect, exit_.state, exit_.faces, owed
                    )
                )
        joined = ExitSet(tuple(exits)).normalize()

        # "On EVERY face" carries the obligation only while there IS a face.
        # Over ZERO faces the same loop puts it nowhere, and the caller would
        # discharge nothing while looking resolved -- the exact silent drop
        # this whole module exists to make loud.
        #
        # Two ways to arrive with nothing left to carry, and this states the
        # property rather than either symptom: an ExitSet that was already
        # empty, and one whose faces `normalize` dropped as provably false.
        # Checked AFTER normalize so it is the surviving faces that answer.
        carried = {
            demand.demand_cid
            for exit_ in joined.exits
            for contract in exit_.pending_contracts
            for demand in contract.demands
        }
        dropped = tuple(
            demand.demand_cid
            for demand in pending.demands
            if demand.demand_cid not in carried
        )
        if not dropped:
            return joined

        from sugar_lift_py_tests.gap.panic import construction_panic_gap as _gap

        _gap(
            owner=owner,
            blame=blame,
            observed=(
                "pending parameter contract demands ("
                + ", ".join(dropped)
                + ") joined onto a partition with no surviving face to carry "
                "them, so the obligation cannot share one carried value"
            ),
            requested="one joined outcome that can carry every pending demand",
            fix=(
                "a partition with no face owes the demand nowhere: give the "
                "obligation a face to be owed on, or refuse the join at the "
                "construction that emptied it -- never let it resolve carrying "
                "nothing"
            ),
        )

    # ANYTHING ELSE stays LOUD: an outcome kind this law has never seen has no
    # arm here by construction, and inventing one would be a guess about where
    # an obligation belongs.
    from sugar_lift_py_tests.gap.info import GapKind
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner=owner,
        blame=blame,
        observed=(
            "pending parameter contract demands ("
            + ", ".join(demand.demand_cid for demand in pending.demands)
            + f") joined onto a {type(outcome).__name__}, which is not a value, "
            "an effect, a second carrier, or a partition"
        ),
        requested="one joined outcome that can carry every pending demand",
        fix=(
            "give this outcome kind an arm that states where the obligation is "
            "owed; never drop the obligation and never owe it on a face that "
            "does not run"
        ),
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
