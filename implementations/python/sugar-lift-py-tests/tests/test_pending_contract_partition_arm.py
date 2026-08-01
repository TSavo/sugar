"""The exit-algebra arm for a pending caller-parameter obligation.

``rewrap_pending`` had four categories and answered three: a value took the
demands back, a second carrier unioned demand sets, an effect carried them
beside itself. A PARTITION panicked -- ``ContractConditionalConstructionV1
.and_then`` joined onto an ``ExitSet`` and had nowhere to put the obligation.

The arm is ``Completed.pending_contracts``, the twin of the field ``Halted``
has carried since #6352. Each law below has a TRUTHFUL twin (the mechanism does
what it claims) and a LYING twin (a plausible weaker mechanism that would still
pass a looser reading), and each names the mechanism it mutates.
"""

import types

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    ContractConditionalConstructionV1,
    merge_demands,
    merge_pending,
    weaken_pending,
)
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.single_outcome_law import rewrap_pending
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort, atomic, ctor, make_var, num
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted, Incomplete
from sugar_lift_py_tests.outcome.exit_set import (
    outcome_to_exitset,
    sole_completed_outcome,
    true_guard,
)

SRC = "blake3-512:" + "a" * 128


def _coordinate(name: str, ordinal: int):
    owner_def = SourceFragmentCoordinateV1(SRC, 1, 0, 10, 4)
    return FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=SRC,
        owner_definition_locus=owner_def,
        declaration_locus=SourceFragmentCoordinateV1(SRC, 1, 17 + ordinal, 1, 22),
        ordinal=ordinal,
        parameter_kind="positional-or-keyword",
        declared_name=name,
        sort=PrimitiveSort("Value"),
    )


def _carrier(name="value", *, ordinal=0, line=3, value="carried"):
    """One pending construction: `<name>[0]`, owing `python:indexable(<name>)`."""
    span = types.SimpleNamespace(
        start_line=line, start_col=9, end_line=line, end_col=17
    )
    site = types.SimpleNamespace(source_cid=SRC, line_col_span=span)
    return ContractConditionalConstructionV1.mint(
        site=site,
        candidate=ctor("py.subscript", [make_var(name), num(0)]),
        demand_formula=atomic("python:indexable", [make_var(name)]),
        value=value,
        coordinate=_coordinate(name, ordinal),
    )


def _guard(name="g"):
    return atomic(f"test:{name}", [make_var("x")])


def _cids(entries):
    return sorted(d.demand_cid for e in entries for d in e.demands)


# ---------------------------------------------------------------- the arm ----


def test_partition_join_puts_the_obligation_on_every_face():
    """TRUTHFUL. Every face of the partition is downstream of the demand."""
    pending = _carrier()
    partitioned = ExitSet(
        (
            Completed(_guard("hot"), "then-value"),
            Halted(_guard("cold"), RaiseEffect('ValueError', 'boom', occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:545:0'))),
        )
    )

    joined = rewrap_pending(
        pending, partitioned, owner="test", blame=pending.source_node
    )

    assert isinstance(joined, ExitSet)
    assert len(joined.exits) == 2
    for exit_ in joined.exits:
        assert _cids(exit_.pending_contracts) == _cids((pending,))


def test_partition_join_does_not_pick_one_face():
    """LYING TWIN. A mechanism that attached the demand to the completed face
    only would satisfy "the obligation survived the join" and still drop it on
    every halted path. Exact cardinality per face: not `>= 1` over the set."""
    pending = _carrier()
    partitioned = ExitSet(
        (
            Completed(_guard("hot"), "then-value"),
            Halted(_guard("cold"), RaiseEffect('ValueError', 'boom', occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:524:0'))),
        )
    )

    joined = rewrap_pending(
        pending, partitioned, owner="test", blame=pending.source_node
    )

    halted = [e for e in joined.exits if isinstance(e, Halted)]
    completed = [e for e in joined.exits if isinstance(e, Completed)]
    assert len(halted) == 1 and len(completed) == 1
    assert len(halted[0].pending_contracts) == 1
    assert len(completed[0].pending_contracts) == 1


def test_partition_join_conserves_an_obligation_the_face_already_owed():
    """TRUTHFUL. A face that already owed something keeps it AND takes the new
    one: two distinct constructions, two carriers, nothing conjoined."""
    already = _carrier("other", ordinal=1, line=7)
    pending = _carrier()
    partitioned = ExitSet(
        (Completed(true_guard(), "v", frozenset(), (already,)),)
    )

    joined = rewrap_pending(
        pending, partitioned, owner="test", blame=pending.source_node
    )

    (arm,) = joined.exits
    assert len(arm.pending_contracts) == 2
    assert _cids(arm.pending_contracts) == sorted(
        _cids((already,)) + _cids((pending,))
    )


def test_partition_join_is_idempotent_on_the_same_construction():
    """TRUTHFUL. The same obligation reaching a join twice through a shared
    outcome DAG is ONE obligation -- `F and F` IS `F`. Exact cardinality: `!= 1`
    would be satisfied by the 2 this is meant to exclude."""
    pending = _carrier()
    partitioned = ExitSet(
        (Completed(true_guard(), "v", frozenset(), (pending,)),)
    )

    joined = rewrap_pending(
        pending, partitioned, owner="test", blame=pending.source_node
    )

    (arm,) = joined.exits
    assert len(arm.pending_contracts) == 1
    assert len(arm.pending_contracts[0].demands) == 1


def test_an_unknown_outcome_kind_is_still_loud():
    """TRUTHFUL. Draining the partition category must not drain the refusal:
    a kind this law has never seen has no arm, and guessing one would invent a
    place for an obligation to be owed."""
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    pending = _carrier()
    with pytest.raises(ConstructionPanic):
        rewrap_pending(
            pending, object(), owner="test", blame=pending.source_node
        )


# ------------------------------------------------------ conservation laws ----


def test_exitset_guarded_conserves_what_each_arm_owes():
    """TRUTHFUL. `ExitSet.guarded` used to rebuild every arm from guard, effect
    and state alone, dropping `Halted.pending_contracts` one call after #6352
    conserved it across the effect -> halted conversion."""
    pending = _carrier()
    before = ExitSet(
        (
            Halted(
                true_guard(),
                RaiseEffect('ValueError', 'boom', occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:504:0')),
                None,
                frozenset(),
                (pending,),
            ),
        )
    )

    after = before.guarded(_guard("branch"))

    (arm,) = after.exits
    assert _cids(arm.pending_contracts) == _cids((pending,))


def test_sequence_carries_the_prefix_obligation_onto_every_tail_exit():
    """TRUTHFUL. The prefix incurred it before the tail ran, so every
    continuation of that path owes it."""
    pending = _carrier()
    prefix = ExitSet((Completed(true_guard(), "v", frozenset(), (pending,)),))

    def step(_value):
        return ExitSet(
            (
                Completed(_guard("ok"), "tail"),
                Halted(_guard("bad"), RaiseEffect('KeyError', 'k', occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:208:0'))),
            )
        )

    after = prefix.sequence(step)

    assert len(after.exits) == 2
    for exit_ in after.exits:
        assert _cids(exit_.pending_contracts) == _cids((pending,))


def test_factoring_unions_obligations_rather_than_intersecting_them():
    """LYING TWIN of the `faces` rule. Partition testimony INTERSECTS on a
    factored arm -- a claim true of one arm says nothing about the merged face.
    Copying that rule to obligations would drop every obligation any single arm
    owed, which is exactly backwards: the arm that owes is still reachable
    inside the factored face."""
    left = _carrier("left", ordinal=0, line=3)
    right = _carrier("right", ordinal=1, line=4)
    g = _guard("pick")
    before = ExitSet(
        (
            Completed(g, "a", frozenset(), (left,)),
            Completed(
                __import__(
                    "sugar_lift_py_tests.ir", fromlist=["not_"]
                ).not_(g),
                "b",
                frozenset(),
                (right,),
            ),
        )
    )

    after = before.factor_completed()

    (arm,) = [e for e in after.exits if isinstance(e, Completed)]
    assert _cids(arm.pending_contracts) == sorted(
        _cids((left,)) + _cids((right,))
    )


def test_arms_owing_different_things_do_not_merge():
    """TRUTHFUL. Obligations are part of the DESTINATION. Two completed arms
    with the same value but different debts are different destinations; merging
    them would keep one debt and drop the other, silently."""
    left = _carrier("left", ordinal=0, line=3)
    right = _carrier("right", ordinal=1, line=4)
    merged = ExitSet(
        (
            Completed(_guard("p"), "same-value", frozenset(), (left,)),
            Completed(_guard("q"), "same-value", frozenset(), (right,)),
        )
    ).normalize()

    assert len(merged.exits) == 2


def test_arms_owing_the_same_thing_still_merge():
    """LYING TWIN of the law above. A mechanism that simply refused to merge any
    arm carrying obligations would pass the previous test while abandoning the
    merge that keeps arm counts linear. Equal debts are one destination."""
    same = _carrier()
    merged = ExitSet(
        (
            Completed(_guard("p"), "same-value", frozenset(), (same,)),
            Completed(_guard("q"), "same-value", frozenset(), (same,)),
        )
    ).normalize()

    assert len(merged.exits) == 1
    assert _cids(merged.exits[0].pending_contracts) == _cids((same,))


# ------------------------------------------------------ the round trip -------


def test_carrier_converts_to_an_exit_set_and_back():
    """TRUTHFUL. `outcome_to_exitset` panicked on a carrier because the algebra
    had no arm for it. With the arm, the conversion is total and the round trip
    through `collapse` returns the same carrier."""
    pending = _carrier()

    exits = outcome_to_exitset(pending)

    (arm,) = exits.exits
    assert isinstance(arm, Completed)
    assert arm.pending_contracts == (pending,)
    assert exits.collapse() == pending


def test_collapse_of_a_clean_arm_is_still_a_bare_complete():
    """LYING TWIN. A mechanism that routed EVERY completed arm through the
    carrier would satisfy the round trip above and change the shape of every
    ordinary block. An arm owing nothing collapses to `Complete`."""
    assert ExitSet.completed("v").collapse() == Complete("v")


def test_collapse_of_a_halted_arm_carries_its_obligations():
    """TRUTHFUL. `Incomplete(effect)` has a field for the debt; using the
    one-argument form here would drop it at the exit of the algebra."""
    pending = _carrier()
    effect = RaiseEffect('ValueError', 'boom', occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:484:0'))
    exits = ExitSet((Halted(true_guard(), effect, None, frozenset(), (pending,)),))

    collapsed = exits.collapse()

    assert isinstance(collapsed, Incomplete)
    assert _cids(collapsed.pending_contracts) == _cids((pending,))


def test_sole_completed_outcome_projects_onto_the_carrier():
    """TRUTHFUL. The success path still owes what it incurred; `Complete` has
    no field for it."""
    pending = _carrier()
    exits = ExitSet((Completed(true_guard(), "v", frozenset(), (pending,)),))

    projected = sole_completed_outcome(exits)

    assert isinstance(projected, ContractConditionalConstructionV1)
    assert projected.value == "v"
    assert _cids((projected,)) == _cids((pending,))


def test_sole_completed_outcome_refuses_two_distinct_constructions():
    """TRUTHFUL. A linear carrier holds ONE candidate and every demand in it
    carries that candidate's address, so fusing two would attribute one
    construction's obligations to another's candidate."""
    exits = ExitSet(
        (
            Completed(
                true_guard(),
                "v",
                frozenset(),
                (_carrier("left", ordinal=0, line=3), _carrier("right", ordinal=1, line=4)),
            ),
        )
    )

    with pytest.raises(ValueError, match="distinct pending constructions"):
        sole_completed_outcome(exits)


# ------------------------------------------------------------- the union -----


def test_merge_pending_keys_on_candidate_not_arrival():
    """TRUTHFUL. Ordering is by content address so two folds that ran in a
    different order mint the same rows."""
    left = _carrier("left", ordinal=0, line=3)
    right = _carrier("right", ordinal=1, line=4)

    assert merge_pending((left,), (right,)) == merge_pending((right,), (left,))


def test_merge_pending_unions_demand_sets_of_one_candidate():
    """TRUTHFUL. Same candidate reaching a join twice under different guards is
    ONE carrier owing BOTH obligations -- never two carriers, never one
    conjoined demand."""
    base = _carrier()
    a = base.demanded_under(_guard("p"))
    b = base.demanded_under(_guard("q"))

    (fused,) = merge_pending((a,), (b,))

    assert len(fused.demands) == 2
    assert fused.demands == merge_demands(a.demands, b.demands)


def test_weaken_pending_weakens_every_carrier():
    """LYING TWIN. Weakening only the first entry would still 'weaken the
    group'; the rest would then be owed unconditionally on a face that may
    never run, which is STRONGER than the source states."""
    group = (_carrier("left", ordinal=0, line=3), _carrier("right", ordinal=1, line=4))

    weakened = weaken_pending(group, _guard("branch"))

    assert len(weakened) == 2
    assert set(_cids(weakened)).isdisjoint(_cids(group))


# ------------------------------------------- the nested-statement splice -----


def _block(entries=()):
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    return _ReducedBlock(entries=tuple(entries), can_fall_through=True, fall_through=())


class _StatementReducingToExitSet:
    """A statement sugar whose `desugar` hands back its OWN ExitSet.

    This is the shape the nested-statement seam exists for -- a try/with whose
    body was reduced separately -- reduced to the smallest thing that reaches
    it. A stub, not vendor source: the seam is what is under test, not any
    particular statement.
    """

    def __init__(self, exits):
        self._exits = exits

    def desugar(self, ctx):
        del ctx
        return self._exits


def test_the_nested_statement_splice_conserves_faces_and_obligations():
    """TRUTHFUL. The rebuild at the nested-statement seam stated three fields,
    so it dropped BOTH the arm's partition testimony and its pending
    obligations -- the same shape of loss `ExitSet.guarded` had.

    Driven through `reduce_block_to_exitset`, not re-implemented here: a control
    that copies the rebuild into itself cannot fail when the rebuild changes,
    which is exactly the twin that proves nothing."""
    from sugar_lift_py_tests.outcome.exit_set import PartitionFace
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        _ReducedBlock,
        reduce_block_to_exitset,
    )

    pending = _carrier()
    face = PartitionFace(("test-origin",), "left", 2)
    inner = _ReducedBlock(("inner-entry",), False, ())
    statement = _StatementReducingToExitSet(
        ExitSet(
            (
                Halted(
                    _guard("h"),
                    RaiseEffect('ValueError', 'boom', occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:437:0')),
                    inner,
                    frozenset({face}),
                    (pending,),
                ),
            )
        )
    )

    reduced = reduce_block_to_exitset((statement,))

    halted = [e for e in reduced.exits if isinstance(e, Halted)]
    assert len(halted) == 1
    arm = halted[0]
    # The obligation reached the block record: enrolment moved it into the
    # arm's entries and cleared the carrier, so the demand rows are the proof.
    owed = [
        entry
        for entry in arm.state.entries
        if isinstance(entry, ContractConditionalConstructionV1)
    ]
    assert len(owed) == 1
    # Enrolment is the ONE mint: the arm holds under `h`, so what reaches the
    # record is `h -> D`, not the bare obligation. Asserting the unweakened cid
    # here would be asserting that the weakening never happened.
    assert _cids(owed) == _cids(weaken_pending((pending,), _guard("h")))
    assert _cids(owed) != _cids((pending,))
    assert face in arm.faces


def test_a_stateless_halt_that_owes_stays_loud():
    """TRUTHFUL. `and_finally`, `and_exit` and `outcome_to_exitset` can all emit
    a halted arm whose state is None. An obligation incurred on that path has no
    record to be owed on, and the gap belongs to the producer that built the
    arm. Supplying a record here would silence
    `_boundary_halted_edge`'s refusal, which reads `state is None` as "the
    reducer omitted the real pre-halt state"; synthesising one from the demand
    rows would assert a record the producer said was absent."""
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        _enrol_exit_obligations,
    )

    owing = ExitSet(
        (
            Halted(
                true_guard(),
                RaiseEffect('ValueError', 'boom', occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:310:0')),
                None,
                frozenset(),
                (_carrier(),),
            ),
        )
    )

    with pytest.raises(ConstructionPanic):
        _enrol_exit_obligations(owing)


def test_an_arm_owing_nothing_never_reaches_the_refusal():
    """LYING TWIN. A mechanism that panicked on any stateless halt would pass
    the law above and turn every ordinary `raise` inside a `finally` into a
    construction gap. Only an arm that OWES has anything to enrol."""
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        _enrol_exit_obligations,
    )

    clean = ExitSet((Halted(true_guard(), RaiseEffect('ValueError', 'boom', occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:184:0')), None),))

    assert _enrol_exit_obligations(clean) is clean


def test_a_stateless_halt_that_owes_is_given_the_prefix_record():
    """TRUTHFUL. `outcome_to_exitset` converts an `Incomplete` to
    `Halted(guard, effect, None)`; `and_finally` and `and_exit` fan halts the
    same way. An arm with no nested record halted at the TOP of its statement,
    so the block's prefix is the complete temporal record for that path and is
    the record the obligation enrols into. Measured: without this, all three
    `and_then` sites on the slice merely change owner instead of draining."""
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        _ReducedBlock,
        _halt_state,
    )

    prefix = _ReducedBlock(("earlier-entry",), True, ())
    owing = Halted(
        true_guard(),
        RaiseEffect('ValueError', 'boom', occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:106:0')),
        None,
        frozenset(),
        (_carrier(),),
    )

    carried = _halt_state(prefix, owing)

    assert isinstance(carried, _ReducedBlock)
    assert carried.entries == ("earlier-entry",)


def test_a_stateless_halt_that_owes_nothing_keeps_its_state():
    """LYING TWIN. Splicing the prefix onto EVERY stateless halt would satisfy
    the law above and silently move existing temporal testimony: an arm that
    owes nothing needed no record and must keep exactly the state it had."""
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        _ReducedBlock,
        _halt_state,
    )

    clean = Halted(true_guard(), RaiseEffect('ValueError', 'boom', occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:84:0')), None)

    assert _halt_state(_ReducedBlock(("earlier-entry",), True, ()), clean) is None
