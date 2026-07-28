"""`<body> if <test> else <orelse>` -- a conditional EXPRESSION (a value).

This is the value the phi produces: `If.substitution_binding` rewrites a
conditionally-bound name to an `IfExp`, so an `IfExp` lands anywhere a value can
(`return (5 if c else 6)`, `assert (5 if c else 6) == x`, `(5 if c else 6) + 1`).

The value is a `GuardedValue(guard, when_true, when_false)` -- the SAME conditional
floor value the predicate join bindings already produce. It is not an ite term:
operations DISTRIBUTE into both arms (`GuardedValue._map`) and a return/equality
splits into `(c -> out == then) AND (not c -> out == else)` via `post_formula` /
`equals`, each arm's equality resolved PER ATOM by `resolve_equality_atom`. So the
"what one sort is the conditional" question never forms -- the value resolves
itself, and a mixed Int/Real conditional is two per-atom equalities each carrying
its own `to_real` bridge, never a single mixed-sort term. (Only a genuinely
opaque collapse -- the conditional as an argument to an EUF function -- folds to
a `py.conditional` term; there an integer arm promotes to Real, since 5 == 5.0.)
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair
from sugar_lift_py_tests.sugar.if_sugar import predicate_formula


@dataclass(frozen=True)
class IfExpSugar(Sugar):
    """`<body> if <test> else <orelse>`, constructed by `IfExp.sugar()` with the
    test's and both arms' sugars already built."""

    test: Sugar
    body: Sugar  # the then-value
    orelse: Sugar  # the else-value
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        # A conditional return: the post distributes to z == 1 -> out == 10, so
        # the caller's A(1) == 10 discharges and A(1) == 11 contradicts.
        return _call_return_pair(
            name="ifexp_conditional_return",
            owner_sugar="IfExpSugar",
            body="10 if z == 1 else 20",
            truthful="10",
            lying="11",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # The test itself can halt or partition (`(a if f() else b)` where the
        # call is unresolvable, `(a if (d[k] := c) else b)`): thread it through
        # `and_then` rather than reading `cond.value`.
        return self.test.desugar(ctx).and_then(
            lambda cond_value: self._join(cond_value, ctx)
        )

    def _join(self, cond_value, ctx) -> Outcome:
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard

        # The guard is the test's TRUTHINESS as a predicate -- uniform via
        # `.truth`: a predicate test (`5 if a == b else 6`) stands as its formula,
        # a bare value (`5 if c else 6`) emits `py.truthy(c)`. A ground-bool test
        # folds to a literal with no formula and is not lifted yet -- LOUD.
        formula = predicate_formula(cond_value, self.site)
        # Ground conditions select one arm before the peer reduces — same law
        # IfSugar owns for statement form. Dual-mode RaisesExc phis
        # (`(T,) if not isinstance(x, tuple) else x`) must collapse to the live
        # TupleValue rather than a GuardedValue/conditional term that later
        # tuple(genexp) cannot floor.
        if formula == true_guard():
            return self.body.desugar(ctx)
        if formula == false_guard():
            return self.orelse.desugar(ctx)
        not_formula = not_(formula)

        then_out = self.body.desugar(ctx)
        else_out = self.orelse.desugar(ctx)

        # A PENDING PARAMETER-CONTRACT ARM (`p[0] if c else 1`, where `p` is a
        # formal) wraps a value together with a demand the linker discharges. The
        # value joins normally; the demand rides back out on the joined result,
        # weakened to the arm's own face -- a caller that never takes the arm owes
        # nothing. `demanded_under` weakens the demand WITHOUT guarding the value,
        # because the join below guards the value itself.
        pending = _pending(then_out), _pending(else_out)
        if any(pending):
            if all(pending):
                # BOTH ARMS PENDING (#6352). `p[0] if c else q[1]` owes
                # `c -> python:indexable(p)` AND `not c -> python:indexable(q)`
                # -- two obligations, each on its own face. This used to be
                # loud, because the carrier held exactly one demand.
                #
                # Each arm weakens under ITS OWN face before the union, so
                # neither is owed where it does not run, and the sets union by
                # content address. The then arm's value carries the joined set.
                from dataclasses import replace

                from sugar_lift_py_tests.caller_parameter_contract import (
                    merge_demands,
                )

                then_entry = then_out.demanded_under(formula)
                else_entry = else_out.demanded_under(not_formula)
                joined = replace(
                    then_entry,
                    demands=merge_demands(then_entry.demands, else_entry.demands),
                )
                return joined.and_then(
                    lambda value: self._join_arms(
                        formula, Complete(value), Complete(else_entry.value)
                    )
                )
            if pending[0]:
                return then_out.demanded_under(formula).and_then(
                    lambda value: self._join_arms(formula, Complete(value), else_out)
                )
            return else_out.demanded_under(not_formula).and_then(
                lambda value: self._join_arms(formula, then_out, Complete(value))
            )
        return self._join_arms(formula, then_out, else_out)

    def _join_arms(self, formula, then_out, else_out) -> Outcome:
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome.exit_set import (
            outcome_to_exitset,
            partition as _partition,
        )

        not_formula = not_(formula)

        # BOTH ARMS ARE ONE VALUE: the fused conditional floor value, exactly as
        # before. GuardedValue is the shape the whole design rests on --
        # operations distribute into both arms and an equality resolves per atom
        # -- so it is kept for the case that can carry it, never widened away.
        if isinstance(then_out, Complete) and isinstance(else_out, Complete):
            return Complete(GuardedValue(formula, then_out.value, else_out.value))

        # AN ARM HALTS OR PARTITIONS. `(a if c else raise)`, `(f() if c else b)`
        # with an unresolvable call, `(a if c else d[k] := v)`. Under `c` the
        # expression IS `a`; under `not c` control leaves with the arm's effect.
        # That is a partition of reachable execution, which is precisely an
        # ExitSet -- the same union `IfSugar` builds for the statement form.
        #
        # This was `NotImplementedError: a conditional-expression arm that
        # reduces to an effect is not lifted yet`. It was never missing meaning:
        # the meaning is the union, and refusing it discarded the arm that DOES
        # produce a value together with the arm that halts. Nothing here folds an
        # effect into a value; each arm stays on its own face under its own
        # guard, and every input arm is conserved into exactly one output arm.
        #
        # This site OWNS the split, so it mints the partition and stamps each
        # arm with its face. A conditional expression is exactly what reaches
        # spread/call operands, where ``factor_completed`` needs the exclusion;
        # by then the guards have been conjoined with a prefix and their shape
        # no longer shows it. Testimony carried here does not decay.
        then_face, else_face = _partition(("IfExpSugar", self.site, formula))
        exits = outcome_to_exitset(then_out).guarded(formula, then_face)
        exits = exits.union(
            outcome_to_exitset(else_out).guarded(not_formula, else_face)
        )

        # FACTOR THE COMPLETED FACE (#6324). An EXPRESSION's exit set is consumed
        # by `and_then`, and `ExitSet.sequence` appends every exit of the tail
        # under every completed exit of the prefix: a receiver with m completed
        # arms followed by k operands distributes into m ** k arms. Two completed
        # arms here is not a small number downstream -- it is the base of an
        # exponent. The corpus measured it: one union at this line arrived with
        # 131,364 arms on `pandas/tests/extension/test_arrow.py`, reached through
        # `method_call_sugar._collect`'s operand chain, and the file crossed a
        # 300s deadline on an idle 32-core box.
        #
        # Factoring moves the SAME partition from the exit level to the value
        # level -- one arm carrying a `GuardedValue` chain -- where k steps
        # contribute k guarded values instead of m ** k arms. Same denotation,
        # linear growth. It is the primitive #6315 built for exactly this and
        # until now had exactly one caller (`SpreadSugar`); the conditional
        # expression is the second producer of a multi-arm completed face, and it
        # reached `sequence` without passing through it.
        #
        # `factor_completed` REFUSES (`ExitSetFactoringGap`) when the completed
        # arms are not provably pairwise exclusive, and that refusal is kept: the
        # two faces here are guarded by `formula` and `not formula`, so a chain
        # that is first-match-wins carries them exactly. Nothing is capped,
        # nothing is pruned, no arm is dropped, and no halted arm is touched --
        # the halted face already grows linearly at the exit level.
        exits = exits.factor_completed()  # `factored_operand`'s half that stays an ExitSet

        # A partition with a single completed face and no halt is a plain value
        # again (normalize may have merged the faces): collapse rather than hand
        # callers a one-arm ExitSet they would have to unwrap. Anything still
        # partitioned stays partitioned -- a caller threads it with `and_then`,
        # which is how every other partition in the lift is consumed.
        return exits.collapse()


def _pending(outcome):
    """The outcome as a pending parameter-contract entry, or ``None``.

    A pending entry is an ``Outcome`` variant that WRAPS a value: it is neither a
    plain value nor a partition, so it has no arm in the exit algebra
    (``outcome_to_exitset`` refuses it). It is unwrapped before the join and
    re-wrapped after.
    """
    from sugar_lift_py_tests.caller_parameter_contract import (
        ContractConditionalConstructionV1,
    )

    return outcome if isinstance(outcome, ContractConditionalConstructionV1) else None
