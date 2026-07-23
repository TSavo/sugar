"""`if <test>: <then> [else: <else>]` -- the GUARD half of an if statement.

An if splits the universe. Its condition desugars to a predicate; each branch's
stated facts are then GUARDED by the branch polarity, and a guarded fact IS an
implication (`InvValue.guarded`): `if c: assert P` emits `c -> P`, `if c: return
E` emits the guarded post `c -> out == E`, `if c: raise X` emits the raise
effect red under `c`. That is the whole of `if`'s MEANING.

The other half of an if -- what a name BINDS to after the branch (the phi
`x = then_x if c else else_x`) -- is temporal, and lives entirely in
`If.substitute` as an `IfExp` rewrite. So this sugar does NO binding join:
`joined_bindings`/`guarded_bindings` on the `GuardedFaces` it builds are empty
by construction. substitute ages the bindings; this reads off the guarded facts.

The factory drove the guard through `PredicateValue.binary_conditional`, but that
path referenced `reduce_with_scope`, which the factory nuke deleted -- it is dead
code. The guard here is written fresh from the pure-meaning primitives that
survived: `reduce_statements` (block reduction), `entry.guarded(formula)`
(implication), and the `GuardedFaces` floor value the block reducer already
consumes.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


def predicate_formula(value, site):
    """The one truth-to-formula projection shared by all guarded constructs."""
    from sugar_lift_py_tests.outcome import Complete

    truth = value.truth(site)
    if not isinstance(truth, Complete):
        raise NotImplementedError(
            f"condition truth did not produce one value: {type(truth).__name__}"
        )
    formula = getattr(truth.value, "formula", None)
    if formula is None:
        from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if isinstance(truth.value, TrueBoolLiteralSugar):
            return true_guard()
        if isinstance(truth.value, FalseBoolLiteralSugar):
            return false_guard()
        raise NotImplementedError(
            f"condition folded without a symbolic formula: {type(value).__name__}"
        )
    return formula


@dataclass(frozen=True)
class IfSugar(Sugar):
    """`if <test>: <then> [else: <else>]`, constructed by `If.sugar()` with the
    test's sugar and each branch's statement sugars already built."""

    test: Sugar
    branch_slot: object
    then_body: tuple  # the then-branch statements' sugars, in source order
    else_body: tuple  # the else-branch statements' sugars (empty if no else)
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        # A guarded return: under the guard the post is `z == 1 -> out == 10`, so
        # the caller's `A(1) == 10` discharges and `A(1) == 11` contradicts.
        return _call_return_pair(
            name="if_guarded_return",
            owner_sugar="IfSugar",
            body="10 if z == 1 else 20",
            truthful="10",
            lying="11",
            prefix="",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.branch_result_coordinate import (
            BranchResultAuthentication,
            branch_result_guard,
        )
        from sugar_lift_py_tests.floor.guarded_faces import GuardedFaces
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import Completed, Halted, Incomplete
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        # Branches carry facts/effects: the guard is the condition's TRUTHINESS
        # as a predicate. `.truth` is uniform -- a predicate condition (`if a ==
        # b`) stands as its own formula, a bare value (`if c`) emits the Python
        # `py.truthy(c)` relation. A ground bool (`if True:`) folds to a literal
        # with no formula and is not lifted yet -- LOUD, never guard by nothing.
        cond = self.test.desugar(ctx)
        if not isinstance(cond, Complete):
            return cond
        observed_formula = predicate_formula(cond.value, self.site)
        formula = branch_result_guard(self.branch_slot, self.site)
        authentication = BranchResultAuthentication(
            self.branch_slot, observed_formula, self.site
        )

        then_exits = reduce_block_to_exitset(self.then_body)
        else_exits = reduce_block_to_exitset(self.else_body)

        # If is union in the exit algebra: each branch is restricted to its
        # polarity, then the partitions normalize together. In particular, a
        # halt on one face coexists with the complementary Completed exit.
        not_formula = not_(formula)
        exits = then_exits.guarded(formula).union(else_exits.guarded(not_formula))
        entries = []
        for exit_ in exits.exits:
            if isinstance(exit_, Halted):
                entries.append(Incomplete(exit_.effect).guarded(exit_.guard))
            else:
                entries.extend(
                    entry.guarded(exit_.guard) for entry in exit_.value.entries
                )

        def can_fall_through(branch_exits):
            return any(
                isinstance(exit_, Completed) and exit_.value.can_fall_through
                for exit_ in branch_exits.exits
            )

        then_branch_exits = not can_fall_through(then_exits)
        else_branch_exits = not can_fall_through(else_exits)
        can_fall_through = not (then_branch_exits and else_branch_exits)
        # The tail rides under the polarity of whichever branch did NOT exit; if
        # both fall through it is unconditional, if both exit it is unreachable.
        continuation_guard = None
        if then_branch_exits and not else_branch_exits:
            continuation_guard = not_formula
        elif else_branch_exits and not then_branch_exits:
            continuation_guard = formula

        return Complete(
            GuardedFaces(
                guard=formula,
                entries=tuple(entries),
                then_exits=then_branch_exits,
                else_exits=else_branch_exits,
                joined_bindings=(),  # bindings are substitute's job (the IfExp phi)
                guarded_bindings=(),
                can_fall_through=can_fall_through,
                continuation_guard=continuation_guard,
                unconditional_entries=(authentication,),
            )
        )
