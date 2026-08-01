"""The demand SET and the effect face: #6352's two closed construction panics.

One expression can incur SEVERAL caller obligations. `[p[0], q[1]]` owes
`python:indexable(p)` AND `python:indexable(q)`. `ContractConditionalConstructionV1`
held exactly one demand, so every join that met a second one panicked NAMED --
`collection TupleValue`, `IfExpSugar._join`, and
`ContractConditionalConstructionV1.and_then` each said the same sentence in its
own `fix` string: "widen ContractConditionalConstructionV1 to carry a demand
SET". Three call sites asking for one widening is the ontology reporting that it
is missing a kind of thing.

The other face: `o.x = p[k]` evaluates `p[k]` -- incurring the obligation -- and
THEN answers with a store effect. The demand was owed on the path that reached
the effect, and `Incomplete` had nowhere to carry it.

Measured on `pandas/core/generic.py` with `scripts/stablezero_classify.py`,
223 functions, isolated:

    main 31ca5580c   construction_panics = 3
    this branch      construction_panics = 0

EVERY TEST HERE IS A PAIR. A positive says the obligation survives; a
DISCRIMINATING one says it survived *as itself*. Widening a carrier is exactly
the change that can pass a positive while quietly losing an obligation --
conjoin two demands into one, keep the first and drop the second, or owe a
demand on a face that never runs. Each of those would satisfy "it lifts" and be
a certified lie about what the caller owes, so each has its own arm below.

The obligations are compared by `demand_cid`: the content address of the WHOLE
demand (owner source identity, formal coordinate, operation site, demanded
formula, candidate). Comparing anything less would let a test pass on a demand
that names the wrong formal.
"""

from __future__ import annotations

import tempfile

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    ContractConditionalConstructionV1,
    merge_demands,
)
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _out(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path)).functions()).sugar().desugar()


def _entries(out) -> tuple:
    """Every projected contract row the function's block record enrolled.

    Read off the record, not off the in-flight carrier, because the record is
    what `link_unit_projection` hands the linker. A demand that never reaches
    here is never discharged, so this is the only honest place to assert
    conservation.

    A function containing a STORE reduces to an `ExitSet`, not a `Complete`:
    `o.x = v` is runtime-selected success/halt over the store's own occurrence
    coordinate. The record lives on the completed face; the halted face carries
    the prefix state and projects no link unit at all.
    """
    from sugar_lift_py_tests.floor.universe_value import UniverseValue
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet

    if isinstance(out, ExitSet):
        completed = [e for e in out.exits if isinstance(e, Completed)]
        assert len(completed) == 1, out
        universe = completed[0].value
    else:
        assert isinstance(out, Complete), out
        universe = out.value
    assert isinstance(universe, UniverseValue), universe
    return tuple(
        row
        for row in universe.record.statements
        if isinstance(row, ContractConditionalConstructionV1)
    )


def _demand_cids(out) -> set[str]:
    return {
        demand.demand_cid for entry in _entries(out) for demand in entry.demands
    }


def _formal_cids(out) -> set[str]:
    return {
        demand.formal_coordinate_cid
        for entry in _entries(out)
        for demand in entry.demands
    }


# --------------------------------------------------------------------------
# The set: union, dedupe, order
# --------------------------------------------------------------------------


def test_two_formals_subscripted_in_one_collection_owe_two_demands():
    """POSITIVE. `[p[0], q[1]]` used to panic `collection TupleValue`.

    Two DISTINCT obligations against two DISTINCT formals. Both are owed.
    """
    out = _out("def f(p, q):\n return [p[0], q[1]]\n")

    assert len(_demand_cids(out)) == 2
    assert len(_formal_cids(out)) == 2


def test_one_formal_subscripted_at_two_sites_owes_two_demands():
    """DISCRIMINATING, and it cuts the other way than it first looks.

    `[p[0], p[0]]` is TWO obligations, not one. `demand_cid` addresses the whole
    demand INCLUDING `operation_site` and `candidate_cid`, and the two `p[0]`
    occupy different source coordinates, so they are two candidates the linker
    resolves independently. Collapsing them because the formal and the formula
    match would discharge one site with the other's resolution.

    The idempotent case is a genuinely SHARED outcome -- one reduced value
    reaching a join twice through the same DAG node -- which is asserted on
    `merge_demands` directly below, where the sharing can be stated exactly
    rather than hoped for from source text.
    """
    out = _out("def f(p):\n return [p[0], p[0]]\n")

    assert len(_demand_cids(out)) == 2
    assert len(_formal_cids(out)) == 1


def test_the_same_obligation_reaching_a_join_twice_unions_to_one():
    """DISCRIMINATING. Content, not arrivals: `F and F` IS `F`.

    A union that counted arrivals would mint a duplicate row and ask the linker
    to discharge one obligation twice.
    """
    out = _out("def f(p):\n return [p[0]]\n")
    (entry,) = _entries(out)

    assert len(merge_demands(entry.demands, entry.demands)) == 1


def test_two_formals_in_one_call_owe_two_demands():
    """POSITIVE. The same law through the CALL fold, not the collection fold.

    `method_call_sugar._collect` threads arguments through the identical
    `and_then` shape, so a law fixed only in `collection_sugar` would leave this
    red.
    """
    out = _out("def f(p, q, g):\n return g(p[0], q[1])\n")

    assert len(_demand_cids(out)) == 2


def test_neither_demand_is_conjoined_into_the_other():
    """DISCRIMINATING. Two demands must stay TWO, each owning its own formal.

    Folding `F1` and `F2` into one demand carrying `F1 and F2` would keep both
    formulas and still be a lie: the surviving demand names ONE
    `formal_coordinate_cid`, so the obligation would be attributed to a formal
    that does not own half of it. That is a fabricated fact, and it would pass
    every count-based assertion above if the count happened to be right.
    """
    out = _out("def f(p, q):\n return [p[0], q[1]]\n")
    formals = _formal_cids(out)

    assert len(formals) == 2, (
        "two obligations collapsed onto one formal coordinate: the demands were "
        "conjoined instead of unioned (#6352)"
    )


def test_merge_is_ordered_by_content_not_by_arrival():
    """DISCRIMINATING. The universe is content; arrival order is not a fact.

    The same two obligations reached in either order must produce the same
    tuple. An arrival-ordered set would make one source mint two different row
    orders depending on which fold ran first, with no RNG and no clock to
    justify the difference.
    """
    forward = _out("def f(p, q):\n return [p[0], q[1]]\n")
    reverse = _out("def f(p, q):\n return [q[1], p[0]]\n")

    entries_forward = _entries(forward)
    entries_reverse = _entries(reverse)
    assert entries_forward and entries_reverse

    both = merge_demands(
        tuple(d for e in entries_forward for d in e.demands),
        tuple(d for e in entries_reverse for d in e.demands),
    )
    assert [d.demand_cid for d in both] == sorted(d.demand_cid for d in both)


# --------------------------------------------------------------------------
# The projection boundary: the set never reaches the wire
# --------------------------------------------------------------------------


def test_every_projected_row_states_exactly_one_demand():
    """THE WIRE LAW. `contribution` splits the set before anything is projected.

    The link unit and the Rust linker each state one demand per row, and they
    are right to: an obligation is owned by ONE formal coordinate. So the set
    must be an in-flight join carrier only.
    """
    out = _out("def f(p, q):\n return [p[0], q[1]]\n")
    entries = _entries(out)

    assert len(entries) == 2
    for entry in entries:
        assert len(entry.demands) == 1
        assert entry.sole_demand() is entry.demands[0]


def test_a_multi_demand_row_refuses_to_project():
    """DISCRIMINATING. An unsplit row reaching the wire is LOUD, not first-of-set.

    If `sole_demand` quietly returned `demands[0]`, a producer that bypassed
    `contribution` would ship one obligation and silently drop the rest -- the
    exact failure the panic existed to prevent.
    """
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    out = _out("def f(p, q):\n return [p[0], q[1]]\n")
    first, second = _entries(out)
    unsplit = ContractConditionalConstructionV1(
        first.source_node,
        first.candidate,
        first.candidate_cid,
        merge_demands(first.demands, second.demands),
        first.value,
    )

    with pytest.raises(ConstructionPanic) as raised:
        unsplit.to_value()

    assert raised.value.info.owner == "ContractConditionalConstructionV1.sole_demand"


# --------------------------------------------------------------------------
# The effect face
# --------------------------------------------------------------------------


def test_a_demand_incurred_before_a_store_effect_is_still_owed():
    """POSITIVE. `o.x = p[k]` used to panic `...and_then` onto an Incomplete.

    `p[k]` is evaluated, incurring `python:indexable(p)`, and THEN the store
    answers with an effect. The obligation was incurred on the path that
    reached the effect, so it is owed, and it must reach the block record.
    """
    out = _out("def f(o, p, k):\n o.x = p[k]\n return 1\n")

    assert len(_demand_cids(out)) == 1


def test_the_effect_itself_is_not_altered_by_the_carried_demand():
    """DISCRIMINATING. The effect stays pristine.

    `pending_contracts` is wrapper-level testimony, exactly as
    `branch_conditions` is. Smashing the obligation into the effect's reason
    would keep the demand visible in a report while corrupting the typed effect
    every downstream arm dispatches on.
    """
    from sugar_lift_py_tests.effect import RaiseEffect

    effect = RaiseEffect.for_builtin('ValueError', occurrence='implementations/python/sugar-source-tree/tests/test_parameter_contract_demand_set.py:476:0')
    bare = Incomplete(effect)
    carrying = Incomplete(effect, (), ("sentinel-entry",))

    assert carrying.effect == bare.effect
    assert carrying.reason == bare.reason


def test_a_guarded_effect_weakens_its_carried_demand_onto_the_same_face():
    """DISCRIMINATING. The demand is owed only where the branch runs.

    `if c: o.x = p[k]` owes `c -> python:indexable(p)`, never the unconditional
    obligation. An implementation that carried the demand through `guarded`
    WITHOUT weakening it would keep every count above green while owing more
    than the source states -- the caller would have to prove indexability on a
    path it never takes.
    """
    guarded = _out("def f(o, p, k, c):\n if c:\n  o.x = p[k]\n return 1\n")
    plain = _out("def f(o, p, k):\n o.x = p[k]\n return 1\n")

    guarded_cids = _demand_cids(guarded)
    plain_cids = _demand_cids(plain)

    assert len(guarded_cids) == 1
    assert len(plain_cids) == 1
    # Weakening RE-MINTS the demand: it IS a different obligation, so its
    # content address must differ from the unconditional one.
    assert guarded_cids != plain_cids


# --------------------------------------------------------------------------
# The residual that is NOT closed, pinned so it cannot go quiet
# --------------------------------------------------------------------------


def test_a_demand_joined_onto_a_partition_stays_loud_and_named():
    """THE PRESERVED REFUSAL. A partition still has no seam for one carried value.

    An `ExitSet`'s faces each carry their own guard. Attributing the obligation
    to every face owes more than the source states; picking one face drops the
    rest. Neither is a smaller answer, so no arm is invented and the gap stays
    named -- with the owner and the replacement architecture in the message.

    This is deliberately still red territory: it is the honest residual, and
    this test exists so that closing it later is a decision someone makes, not
    something that happens by accident.
    """
    from sugar_lift_py_tests.floor.single_outcome_law import rewrap_pending
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    out = _out("def f(p):\n return [p[0]]\n")
    entry = _entries(out)[0]

    with pytest.raises(ConstructionPanic) as raised:
        rewrap_pending(
            entry,
            ExitSet(()),
            owner="test_partition_face",
            blame=entry.source_node,
        )

    info = raised.value.info
    assert info.owner == "test_partition_face"
    assert "ExitSet" in info.observed
    assert "never drop the obligation" in info.fix


def test_an_effect_face_is_no_longer_the_partition_gap():
    """DISCRIMINATING for the test above: the two faces are DIFFERENT laws.

    An `Incomplete` now carries the obligation; only an `ExitSet` refuses. If
    both went down the same arm, the effect fix would be invisible and the
    refusal test above would pass for the wrong reason.
    """
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.floor.single_outcome_law import rewrap_pending

    out = _out("def f(p):\n return [p[0]]\n")
    entry = _entries(out)[0]

    joined = rewrap_pending(
        entry,
        Incomplete(RaiseEffect.for_builtin('ValueError', occurrence='implementations/python/sugar-source-tree/tests/test_parameter_contract_demand_set.py:441:0')),
        owner="test_effect_face",
        blame=entry.source_node,
    )

    assert isinstance(joined, Incomplete)
    assert joined.pending_contracts == (entry,)


# --------------------------------------------------------------------------
# The conversion boundary: an obligation must not vanish becoming a halted arm
#
# This is its own named thing, not a side effect of the arm below. A demand
# that disappears at an `Incomplete` -> `Halted` conversion is unattributable
# afterward: no caller owes it, no linker discharges it, and NOTHING reports
# it. A silent loss on a conversion boundary is the worst shape a bug can
# take here, which is why it gets its own twins rather than riding on the
# tests for the arm that exposed it.
# --------------------------------------------------------------------------


def _halted_carrier(guard=None):
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.outcome.exit_set import Halted, outcome_to_exitset

    out = _out("def f(p):\n return [p[0]]\n")
    (entry,) = _entries(out)
    effect = RaiseEffect.for_builtin('ValueError', occurrence='implementations/python/sugar-source-tree/tests/test_parameter_contract_demand_set.py:385:0')
    incomplete = Incomplete(effect, (guard,) if guard is not None else (), (entry,))
    exits = outcome_to_exitset(incomplete)
    (arm,) = exits.exits
    assert isinstance(arm, Halted)
    return entry, arm


def test_an_obligation_survives_the_effect_to_halted_conversion():
    """POSITIVE. `outcome_to_exitset` used to build the arm from `effect` alone.

    Everything else on the `Incomplete` -- the obligations it had already
    incurred -- was dropped on the floor at the conversion, with no panic, no
    row and no way to notice.
    """
    entry, arm = _halted_carrier()

    assert arm.pending_contracts == (entry,)


def test_the_conversion_weakens_the_obligation_under_the_arms_own_guard():
    """DISCRIMINATING. Carrying it UNCONDITIONALLY would also pass the test above.

    The arm holds only under its guard, so the obligation it carries is
    `g -> D`, never the bare `D`. Carrying the bare demand would make a caller
    prove indexability on a path where control never reached the subscript.
    """
    from sugar_lift_py_tests.ir import atomic, make_var

    guard = atomic("branch", [make_var("state")])
    entry, arm = _halted_carrier(guard)

    (carried,) = arm.pending_contracts
    assert carried.demands[0].demand_cid != entry.demands[0].demand_cid, (
        "the obligation crossed the conversion unweakened: it is owed on a face "
        "that may never run (#6352)"
    )


def test_halted_arms_owing_different_things_are_different_destinations():
    """DISCRIMINATING. `normalize` merges equal destinations by DISJOINING guards.

    If obligations were not part of the destination, two halted arms with the
    same effect and state but different demands would merge, and the merge
    keeps the PRIOR's payload -- silently dropping the arrival's obligation.

    They are not intersected either: intersecting drops one, unioning owes one
    on a face that never runs. Neither route is taken, so the arms simply do
    not merge.
    """
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.ir import atomic, make_var
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted

    first = _entries(_out("def f(p):\n return [p[0]]\n"))[0]
    second = _entries(_out("def f(q):\n return [q[1]]\n"))[0]
    effect = RaiseEffect.for_builtin('ValueError', occurrence='implementations/python/sugar-source-tree/tests/test_parameter_contract_demand_set.py:358:0')

    merged = ExitSet(
        (
            Halted(
                atomic("a", [make_var("s")]), effect, None, pending_contracts=(first,)
            ),
            Halted(
                atomic("b", [make_var("s")]), effect, None, pending_contracts=(second,)
            ),
        )
    ).normalize()

    assert len(merged.exits) == 2
    carried = {
        demand.demand_cid
        for arm in merged.exits
        for entry in arm.pending_contracts
        for demand in entry.demands
    }
    assert len(carried) == 2


def test_halted_arms_owing_the_same_thing_still_merge():
    """DISCRIMINATING for the test above: the destination key must not over-split.

    Making every halted arm unique would also make the merge "never drop"
    anything, and would give back the arm growth #6333 removed. Arms with the
    SAME obligations are the same destination and still merge to one.
    """
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.ir import atomic, make_var
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted

    (entry,) = _entries(_out("def f(p):\n return [p[0]]\n"))
    effect = RaiseEffect.for_builtin('ValueError', occurrence='implementations/python/sugar-source-tree/tests/test_parameter_contract_demand_set.py:275:0')

    merged = ExitSet(
        (
            Halted(
                atomic("a", [make_var("s")]), effect, None, pending_contracts=(entry,)
            ),
            Halted(
                atomic("b", [make_var("s")]), effect, None, pending_contracts=(entry,)
            ),
        )
    ).normalize()

    assert len(merged.exits) == 1
    assert merged.exits[0].pending_contracts == (entry,)


# --------------------------------------------------------------------------
# The arm: a carrier reaching the exit algebra names its owner
# --------------------------------------------------------------------------


def test_a_spread_operand_owing_a_contract_lifts_and_keeps_its_demand():
    """POSITIVE. `[*xs, p[0]]` stopped on a bare `TypeError(type(outcome))`.

    `spread_sugar._collect` never hoisted the way `collection_sugar` does, so
    the carrier reached `outcome_to_exitset` and the tower stopped on an
    exception that named no owner, no observed shape and no fix.
    """
    out = _out("def f(xs, p):\n return [*xs, p[0]]\n")

    assert len(_demand_cids(out)) == 1


def test_a_carrier_reaching_the_exit_algebra_names_its_owner_and_its_fix():
    """DISCRIMINATING. The refusal must be a NAMED gap, never a bare exception.

    A producer that forgets to hoist has to be handed the fix, not a
    `TypeError` whose whole content is a type name. An unnamed row is worse
    than the panic it replaced, because it names neither owner nor replacement
    architecture.
    """
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset

    (entry,) = _entries(_out("def f(p):\n return [p[0]]\n"))

    with pytest.raises(ConstructionPanic) as raised:
        outcome_to_exitset(entry)

    info = raised.value.info
    assert info.owner == "outcome_to_exitset"
    assert "pending parameter contract carrier" in info.observed
    assert "rewrap_pending" in info.fix
    assert "never drop the obligation" in info.fix
