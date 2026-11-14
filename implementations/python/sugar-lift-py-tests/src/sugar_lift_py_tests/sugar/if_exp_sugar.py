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

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair
from sugar_lift_py_tests.sugar.if_sugar import predicate_formula


@dataclass(frozen=True)
class IfExpSugar(ConstructedTermSugar):
    """`<body> if <test> else <orelse>`, constructed by `IfExp.sugar()` with the
    test's and both arms' sugars already built."""

    test: ConstructedTermSugar
    body: ConstructedTermSugar  # the then-value
    orelse: ConstructedTermSugar  # the else-value
    site: object = dataclass_field(compare=False, default=None)
    branch_slot: object = None
    # ``(evaluation, name, prior)`` for each walrus in an arm whose name was
    # bound before the expression (``IfExp.substitute``): ``prior`` is the
    # read of that name there.  An arm the walrus did not run on holds the
    # name at that value under the walrus's key (``_holding``).
    walrus_priors: tuple = dataclass_field(compare=False, default=())

    def __post_init__(self) -> None:
        # Defense in depth: construction door is IfExp._construct_sugar, which
        # raises SugarNotWritten for non-term arms. SpreadCollectionSugar is
        # ConstructedTermSugar (to_term admitted). If anything bypasses the
        # door with a bare Sugar arm, refuse the same way — never TypeError.
        from sugar_source_tree.panic import SugarNotWritten

        for arm_name, arm in (
            ("test", self.test),
            ("body", self.body),
            ("orelse", self.orelse),
        ):
            if isinstance(arm, ConstructedTermSugar):
                continue
            raise SugarNotWritten(
                blame=self.site,
                owner=f"IfExpSugar.{arm_name}",
                observed=(
                    f"IfExpSugar.{arm_name} is {type(arm).__name__}, not "
                    "ConstructedTermSugar"
                ),
                requested="ConstructedTermSugar arms for to_term / distribute",
                fix=(
                    "construct only through IfExp._construct_sugar, which names "
                    "the missing arm sugar; do not bypass with a raw type assert"
                ),
            )

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

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:if-expression-construction",
            (
                self.occurrence_term(owner=owner),
                self.test.to_term(owner=owner),
                self.body.to_term(owner=owner),
                self.orelse.to_term(owner=owner),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        # The test itself can halt or partition (`(a if f() else b)` where the
        # call is unresolvable, `(a if (d[k] := c) else b)`): thread it through
        # `and_then` rather than reading `cond.value`.  The test is an operand:
        # a walrus in it (`a if (n := c) else b`) runs before either arm, so
        # through the one operand door its bind rides both arms' values, and
        # both arms are reduced with it bound: an arm reads it through its
        # key (``IfExp.substitute``), never the name.  An arm's own walrus
        # rides that arm's value only; the other arm holds the name's earlier
        # value under that walrus's key (``_holding``).
        from sugar_lift_py_tests.floor.named_expression_value import (
            bind_walrus_binds,
            consume_operands,
            peel_walrus_binds,
        )

        def join(cond_value):
            arm_ctx = bind_walrus_binds(peel_walrus_binds(cond_value)[0], ctx)
            return consume_operands(
                lambda presented: self._join(presented, arm_ctx), cond_value
            )

        return self.test.desugar(ctx).and_then(join)

    def _join(self, cond_value, ctx) -> ExitSet:
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard

        # The guard is the test's TRUTHINESS as a predicate -- uniform via
        # `.truth`: a predicate test (`5 if a == b else 6`) stands as its formula,
        # a bare value (`5 if c else 6`) emits `py.truthy(c)`. A ground-bool test
        # folds to a literal with no formula and is not lifted yet -- LOUD.
        observed_formula = predicate_formula(cond_value, self.site)
        formula = observed_formula
        if self.branch_slot is not None:
            from sugar_lift_py_tests.floor.branch_result_coordinate import (
                branch_result_guard,
            )

            if observed_formula not in (false_guard(), true_guard()):
                formula = branch_result_guard(self.branch_slot, self.site)
        # Ground conditions select one arm before the peer reduces — same law
        # IfSugar owns for statement form. Dual-mode RaisesExc phis
        # (`(T,) if not isinstance(x, tuple) else x`) must collapse to the live
        # TupleValue rather than a GuardedValue/conditional term that later
        # tuple(genexp) cannot floor.
        if formula == true_guard():
            return self._holding(self.body.desugar(ctx), ctx)
        if formula == false_guard():
            return self._holding(self.orelse.desugar(ctx), ctx)
        not_formula = not_(formula)

        then_out = self._holding(self.body.desugar(ctx), ctx)
        else_out = self._holding(self.orelse.desugar(ctx), ctx)

        # A deferred native-operation arm is not an ExitSet. BoolOp keeps that
        # carrier beside the already-decided face via short_circuit. The same
        # law applies here: evaluate the deferred arm only on its face, and
        # keep the completed peer as the stopping face. Do not evaluate
        # exc.message on the path that wrote str(exc). Both-deferred arms stay
        # loud.
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )

        then_deferred = isinstance(then_out, NativeOperationExitCarrierV1)
        else_deferred = isinstance(else_out, NativeOperationExitCarrierV1)
        if then_deferred and else_deferred:
            from sugar_lift_py_tests.gap.info import GapKind
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="IfExpSugar",
                blame=self.site,
                observed="both conditional-expression arms are deferred "
                "native-operation carriers",
                requested="at most one deferred arm beside a decided ExitSet arm",
                fix="retain each carrier through caller discharge",
                gap_kind=GapKind.FLOOR,
            )
        if then_deferred or else_deferred:
            from sugar_lift_py_tests.outcome.exit_set import partition as _partition

            then_face, else_face = _partition(("IfExpSugar", self.site, formula))
            # The decided peer stands under its own polarity, as BoolOp's
            # stopping operand does: it is not a fact on the deferred path.
            if then_deferred:
                return then_out.short_circuit(
                    continuing_guard=formula,
                    stopped=else_out.guarded(not_formula),
                    continuing_face=then_face,
                    stopped_face=else_face,
                )
            return else_out.short_circuit(
                continuing_guard=not_formula,
                stopped=then_out.guarded(formula),
                continuing_face=else_face,
                stopped_face=then_face,
            )
        return self._join_arms(formula, then_out, else_out)

    def _join_arms(self, formula, then_out, else_out) -> ExitSet:
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome.exit_set import partition as _partition
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
        )

        not_formula = not_(formula)

        # BOTH ARMS ARE ONE VALUE: the fused conditional floor value, exactly as
        # before. GuardedValue is the shape the whole design rests on --
        # operations distribute into both arms and an equality resolves per atom
        # -- so it is kept for the case that can carry it, never widened away.
        # Only plain arms fuse: an arm that owes something keeps its own arm
        # below, so its debt is carried.
        from sugar_lift_py_tests.floor.named_expression_value import (
            NamedExpressionValue,
        )
        from sugar_lift_py_tests.outcome import Completed

        then_value = plain_completed_value(then_out)
        else_value = plain_completed_value(else_out)
        # An arm carrying a walrus bind keeps its own arm below: fused, the
        # bind would sit inside the conditional value, where no statement
        # applies it, and each arm's bind belongs to that arm alone.
        if (
            then_value is not None
            and else_value is not None
            and not isinstance(then_value, NamedExpressionValue)
            and not isinstance(else_value, NamedExpressionValue)
        ):
            return ExitSet.completed(GuardedValue(formula, then_value, else_value))

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
        exits = then_out.guarded(formula, then_face)
        exits = exits.union(else_out.guarded(not_formula, else_face))

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
        # A partition with a single completed face and no halt is one arm again
        # (normalize may have merged the faces); anything still partitioned
        # stays partitioned. Either way a caller threads it with `and_then`,
        # which is how every partition in the lift is consumed.
        #
        # A completed arm that carries a walrus bind stays its own arm, one per
        # branch, guarded by the test: factoring would fold the arms' values,
        # and the binds with them, into one guarded value.  The statement
        # applies each arm's binds on that arm (``consume_operands``).
        if any(
            isinstance(arm, Completed) and isinstance(arm.value, NamedExpressionValue)
            for arm in exits.exits
        ):
            return exits
        return exits.factor_completed()

    def _holding(self, outcome, ctx) -> ExitSet:
        """``outcome`` (one arm's), each completed value also carrying, for
        every walrus in either arm that did not bind on it, the name's value
        from before the expression under that walrus's key (a held bind).

        Python leaves ``x`` as it was on the arm where ``(x := 5)`` did not
        run; a later read of ``x`` is a reference to the walrus's key, so on
        that arm the key holds the earlier value.  A held bind after an
        earlier bind of the same name in the same evaluation takes that
        bind's value instead (``peel_walrus_binds``).  A walrus whose name
        was not bound before the expression is held nowhere: the read there
        is refused by name, as Python raises.  Without a walrus in the arms
        this is ``outcome`` itself."""
        if not self.walrus_priors:
            return outcome
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )

        if isinstance(outcome, NativeOperationExitCarrierV1):
            # A deferred arm is answered on its own face (``short_circuit``);
            # nothing is held there, so a read after it is refused by name.
            return outcome
        from sugar_lift_py_tests.floor.named_expression_value import (
            NamedExpressionValue,
            carry_walrus_binds,
            peel_walrus_binds,
        )

        priors: dict = {}

        def prior_value(evaluation, prior):
            # The read of the name before the expression, once per arm.
            if evaluation not in priors:
                read = prior.desugar(ctx)
                value = read.completed_value()
                priors[evaluation] = (
                    None
                    if value is None or read.owed_items()
                    else peel_walrus_binds(value)[1]
                )
            return priors[evaluation]

        def hold(value):
            binds, presented = peel_walrus_binds(value)
            ran = {bind.evaluation for bind in binds}
            held = []
            for evaluation, name, prior in self.walrus_priors:
                if evaluation in ran:
                    continue
                earlier = prior_value(evaluation, prior)
                if earlier is None:
                    continue
                held.append(
                    NamedExpressionValue(
                        name, earlier, evaluation=evaluation, held=True
                    )
                )
            if not held:
                return ExitSet.completed(value)
            return ExitSet.completed(carry_walrus_binds((*binds, *held), presented))

        return outcome.and_then(hold)
