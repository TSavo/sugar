"""#6356's premise was WRONG, and this file is why nobody should retry it.

The theory, from the diagnosis I wrote on the last measurement: the residual
`ExitSetFactoringGap` on `pandas/core/generic.py:13403` survives because
`guarded_binding_read_sugar.read_binding` owns a genuine two-way split
(`GuardedProjection` under `branch_result_guard`) and joins it with a bare
`.guarded(g)` / `.guarded(not g)` union, minting no `PartitionFace` where
`IfSugar` and `IfExpSugar` do. Wire it up, the theory said, and the last
`stableZero` term closes.

I wired it — `read_binding` and `delete_binding`, both verbs, faces keyed by
`slot_id` — and MEASURED. `R(factoring_gaps)` read 1 before and 1 after. The
theory was wrong twice over, and both refutations are pinned below so the next
agent reaches them in seconds instead of an afternoon.

REFUTATION 1: there is nothing for the testimony to add.
`_conjuncts` FLATTENS nested conjunctions, so conjoining a branch-result guard
with any prefix leaves `g` and `not g` as top-level literals and
`_are_exclusive` still sees the complement. The "guards stop spelling the
exclusion once conjoined with a prefix" story — which is true of #6336's
motivating case — is NOT true of a conjunctive prefix. Faces on this producer
would be evidence for something already proven.

REFUTATION 2: the shape that DOES hide it cannot carry testimony either.
The corpus arms that actually refuse are opposed at a slot, but one of them is
a MERGED arm whose conjunct there is a DISJUNCTION (`g or X`, built by
`_or_guards` when `normalize` merged two equal destinations). `complement_guard`
of `g or X` is not `not g`, so the shape test correctly fails — and #6336's
composition rule has ALREADY intersected the faces away on that merge, on
purpose: a merged arm holds under a disjunction, so it may only keep testimony
every contributing arm carried.

Both of those are correct behaviour. The refusal on `generic.py:13403` is
`factor_completed` doing its job: `¬g1 ∧ ¬g2 ∧ (g3 or X)` and
`¬g1 ∧ ¬g2 ∧ ¬g3 ∧ … ∧ g9` can both hold whenever `X` does, so the completed
face there is a SET of simultaneously reachable outcomes, not a selection, and
a first-match-wins `GuardedValue` chain cannot carry it.

So the last `stableZero` term is not a wiring omission. It is either an arm
whose guard is under-constrained upstream of the merge, or a genuinely
non-exclusive face — and the fix belongs to whoever produces that arm, before
it merges. Do not close it by minting faces, by widening `_are_exclusive` to
reason about disjunctions, or by weakening the refusal.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor.branch_result_coordinate import branch_result_guard
from sugar_lift_py_tests.ir import and_, not_, or_
from sugar_lift_py_tests.outcome.exit_set import _are_exclusive, _conjuncts
from sugar_source_tree.binding_state import BranchResultSlot


def _slot(name: str) -> BranchResultSlot:
    return BranchResultSlot(f"branch-result:{name}")


def _guard():
    return branch_result_guard(_slot("a"), site=None)


def _prefix(index: int):
    from sugar_lift_py_tests.ir import atomic, make_var

    return atomic(f"prefix{index}", [make_var("state")])


def test_a_conjoined_prefix_does_not_hide_the_branch_result_exclusion():
    """REFUTATION 1. Faces on `read_binding` would be evidence for the proven.

    If this ever goes red, a conjunctive prefix HAS started hiding the
    exclusion, and minting faces at the branch-result producers becomes worth
    doing after all. Until then it is a no-op and must not be shipped as a fix.
    """
    guard = _guard()
    left = and_([_prefix(0), guard])
    right = and_([_prefix(1), not_(guard)])

    assert _are_exclusive(left, right)


def test_conjuncts_flattens_nested_conjunctions_which_is_why():
    """The mechanism behind refutation 1, asserted directly.

    `_are_exclusive` is one literal deep, and this is what makes that enough
    for every conjunctive nesting the tower builds.
    """
    guard = _guard()
    nested = and_([and_([_prefix(0), _prefix(1)]), and_([guard])])

    assert guard in frozenset(_conjuncts(nested))


def test_a_disjoined_guard_is_not_provably_exclusive_and_must_not_be():
    """REFUTATION 2, and the correctness claim under it.

    A merged arm's conjunct is `g or X`. It genuinely overlaps `not g` whenever
    `X` holds, so the shape test answering False is RIGHT, not shallow. Any
    future attempt to make this pair exclusive is a request to collapse two
    simultaneously reachable outcomes into one.
    """
    guard = _guard()
    merged = and_([_prefix(0), or_([guard, _prefix(9)])])
    sibling = and_([_prefix(0), not_(guard)])

    assert not _are_exclusive(merged, sibling)


def test_the_unmerged_pair_the_disjunction_came_from_is_exclusive():
    """DISCRIMINATING for the test above: the loss happens AT the merge.

    Before `_or_guards` disjoins them the two contributing arms are exclusive
    against the sibling. That is what makes the merge the interesting event and
    the producer the right owner — not the prover, and not the refusal.
    """
    guard = _guard()
    contributing = and_([_prefix(0), guard])
    sibling = and_([_prefix(0), not_(guard)])

    assert _are_exclusive(contributing, sibling)
