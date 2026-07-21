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


@dataclass(frozen=True)
class IfSugar(Sugar):
    """`if <test>: <then> [else: <else>]`, constructed by `If.sugar()` with the
    test's sugar and each branch's statement sugars already built."""

    test: Sugar
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
        from sugar_lift_py_tests.floor.guarded_faces import GuardedFaces
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_statements

        # The condition states a predicate; its formula is the guard. A condition
        # whose value carries no formula (a ground bool, a bare truthiness) is not
        # handled yet -- be LOUD rather than silently guard by nothing.
        cond = self.test.desugar(ctx)
        formula = getattr(getattr(cond, "value", None), "formula", None)
        if formula is None:
            raise NotImplementedError(
                "if-condition without a predicate formula is not lifted yet "
                "(ground bool / bare truthiness): only `if <predicate>:` guards "
                f"today; got {type(getattr(cond, 'value', cond)).__name__}"
            )

        then_entries, _c1, then_falls, _f1 = reduce_statements(self.then_body, ctx)
        else_entries, _c2, else_falls, _f2 = reduce_statements(self.else_body, ctx)

        # Each branch's facts ride under its polarity: then under c, else under ¬c.
        not_formula = not_(formula)
        entries = (
            *(entry.guarded(formula) for entry in then_entries),
            *(entry.guarded(not_formula) for entry in else_entries),
        )

        then_exits = not then_falls
        else_exits = not else_falls
        can_fall_through = not (then_exits and else_exits)
        # The tail rides under the polarity of whichever branch did NOT exit; if
        # both fall through it is unconditional, if both exit it is unreachable.
        continuation_guard = None
        if then_exits and not else_exits:
            continuation_guard = not_formula
        elif else_exits and not then_exits:
            continuation_guard = formula

        return Complete(
            GuardedFaces(
                guard=formula,
                entries=entries,
                then_exits=then_exits,
                else_exits=else_exits,
                joined_bindings=(),  # bindings are substitute's job (the IfExp phi)
                guarded_bindings=(),
                can_fall_through=can_fall_through,
                continuation_guard=continuation_guard,
            )
        )
