"""`if <test>: <then> [else: <else>]` -- the GUARD half of an if statement.

An if splits the universe. Its condition desugars to a predicate; each branch's
stated facts are then GUARDED by the branch polarity, and a guarded fact IS an
implication (`InvValue.guarded`): `if c: assert P` emits `c -> P`, `if c: return
E` emits the guarded post `c -> out == E`, `if c: raise X` emits the raise
effect red under `c`. That is the whole of `if`'s MEANING.

The other half of an if -- what a name BINDS to after the branch (the phi
`x = then_x if c else else_x`) -- is temporal, and lives entirely in
`If.substitute` as an `IfExp` rewrite. So this sugar does NO binding join:
the `GuardedFaces` it builds binds no name. substitute ages the bindings;
this reads off the guarded facts. What it carries out of the arms is the
statement evaluations they made (`_arm_evaluations`), each under the guard
of the arm that made it: the phi's arm is a reference to one of them
(temporal choice 1, #7661).

The guard here is written from the pure-meaning primitives:
`reduce_block_to_exitset` (block reduction), `entry.guarded(formula)`
(implication), and the `GuardedFaces` floor value the block reducer already
consumes. A halt in either suite stays a halted arm of the if's `ExitSet`; the
`GuardedFaces` record holds completed testimony only (#7826).
"""

from __future__ import annotations

import functools

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


def _ground_atomic_truth(formula):
    """Evaluate constant FOL atoms that if-guards must fold before dual arms run.

    ``len(xs) == 1`` over a constructed one-element tuple is ``=(1, 1)`` — a
    decided Python condition. Leaving it symbolic forces IfSugar to reduce both
    arms under the atom, so the false multi-exception ``join`` path panics even
    when source has a singleton. Ground constants are not invented testimony:
    they are the values already present in the equality atom.
    """
    from sugar_lift_py_tests.ir import (
        _Atomic,
        _ConstBool,
        _ConstInt,
        _ConstReal,
        _ConstStr,
    )

    if (
        not isinstance(formula, _Atomic)
        or formula.name != "="
        or len(formula.args) != 2
    ):
        return None
    left, right = formula.args
    const_types = (_ConstInt, _ConstReal, _ConstBool, _ConstStr)
    if type(left) not in const_types or type(right) is not type(left):
        return None
    return left.value == right.value


def predicate_formula(value, site):
    """The one truth-to-formula projection shared by all guarded constructs."""
    from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        plain_completed_value,
    )

    truth = value.truth(site)
    truth_value = plain_completed_value(truth)
    if truth_value is None:
        raise NotImplementedError(
            f"condition truth did not produce one value: {type(truth).__name__}"
        )
    # A truth face that PRESENTS another value (`if (n := c):` -- the walrus keeps
    # its value and bind faces inseparable) is transparent to the guard: the
    # binding is temporal and `extend_scope` applies it, while the GUARD is the
    # presented face's formula. Reading `formula` off the wrapper found nothing
    # and reported `condition folded without a symbolic formula:
    # NamedExpressionValue`, blaming the wrapper for a formula the presented
    # value had all along. Structural: any value that presents another is
    # projected through, with no table of which ones do.
    presented = getattr(truth_value, "presented_value", None)
    if presented is not None:
        truth_value = presented
    formula = getattr(truth_value, "formula", None)
    if formula is None:
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if isinstance(truth_value, TrueBoolLiteralSugar):
            return true_guard()
        if isinstance(truth_value, FalseBoolLiteralSugar):
            return false_guard()
        raise NotImplementedError(
            "condition folded without a symbolic formula: "
            f"{type(truth_value).__name__} (condition {type(value).__name__})"
        )
    ground = _ground_atomic_truth(formula)
    if ground is True:
        return true_guard()
    if ground is False:
        return false_guard()
    return formula


def _is_linear(exits) -> bool:
    """One unguarded completed face: nothing a flattening could merge."""
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    return (
        len(exits.exits) == 1
        and isinstance(exits.exits[0], Completed)
        and exits.exits[0].guard == true_guard()
        and not exits.exits[0].faces
        # An owing arm is not flattened: the flattening drops ``owed``.
        and not exits.exits[0].owed
    )


def _arm_evaluations(arms, incoming) -> tuple:
    """The statement evaluations the completed arms of an if made, each key
    with the value it holds on every path through the ``if``.

    ``arms`` are exit sets whose completed arms are the ``if``'s, each under
    its own guard (the ``if`` hands its own exit set: each suite's arms
    under that suite's polarity).  Each key names one statement's evaluation
    (``AugAssign._evaluation_key``) and a statement sits in one suite, so
    after the ``if`` a key is read only by the phi's arm for that suite
    (``If.substitute``), under that suite's guard.  A walrus in the
    condition (``if (n := e):``) is evaluated before either suite: its key is
    in every arm with the one value, and a read after the ``if`` is no phi's
    arm.  ``incoming`` is the context before the condition, so that key is
    carried too.  A live loop in a suite publishes each name it carries under
    a binding coordinate under its own key
    (``live_loop_construction.loop_post_binding_key``), an evaluation key
    too: it is carried out the same way, and the phi's arm for that suite
    reads it (``LoopBindingRefSugar``).  The ``if`` carries those values
    out; it carries no name.

    One rule for every key (``_joined_evaluation``): the arms that bound it
    answer one value, or each arm's own value under that arm's guard -- a
    loop in a suite that leaves by a ``break`` on one path and by
    exhaustion on another binds its key to a different value on each, and
    the read after the ``if`` takes each path's value under its guard.
    """
    from sugar_lift_py_tests.outcome import Completed

    before = getattr(incoming, "temporal", None)
    made: dict = {}
    for arm in arms:
        for exit_ in getattr(arm, "exits", ()):
            if not isinstance(exit_, Completed):
                continue
            context = getattr(exit_.value, "context", None)
            temporal = getattr(context, "temporal", None)
            if temporal is None:
                continue
            for binding in temporal.evaluations():
                if (
                    before is not None
                    and before.value_if_bound(binding.name) is binding.value
                ):
                    continue
                made.setdefault(binding.name, []).append(
                    Completed(exit_.guard, binding.value, exit_.faces)
                )
    joined = ((key, _joined_evaluation(bound)) for key, bound in made.items())
    return tuple((key, value) for key, value in joined if value is not None)


def _joined_evaluation(arms):
    """One evaluation key's value after the ``if``, from ``arms``: each a
    completed arm of the ``if`` that bound the key, holding the value it
    bound under the arm's guard and faces.

    The arms that bound it to one value answer that value.  Arms that bound
    it to different values answer the guarded value selecting each arm's own
    value under that arm's guard: the completed face factored into one
    ``GuardedValue`` chain through the one door that does it
    (``ExitSet.factor_completed``), which admits it only when the arms are
    provably exclusive.  Arms it cannot prove exclusive hold the key at two
    values on one path: there is no one value to carry, the key is not
    bound, and its read is refused by name (``EvaluationRefSugar``,
    ``LoopBindingRefSugar``), never answered with one of the two.
    """
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import ExitSetFactoringGap

    first = arms[0].value
    if all(arm.value is first for arm in arms):
        return first
    try:
        factored = ExitSet(tuple(arms)).normalize().factor_completed()
    except ExitSetFactoringGap:
        return None
    (arm,) = factored.exits
    return arm.value


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

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )

        cond = self.test.desugar(ctx)
        if isinstance(cond, NativeOperationExitCarrierV1):
            return cond.and_then(lambda value: self._desugar_condition(value, ctx))
        from sugar_lift_py_tests.outcome import Halted
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halt_record,
            halts_recorded,
            plain_completed_value,
        )

        if isinstance(cond, ExitSet) and any(
            isinstance(face, Halted) for face in cond.exits
        ):
            # A condition that may raise (an unknown callee completes or
            # raises): each completed face selects its suites under its own
            # guard; a halted face never reaches either suite. Returning the
            # condition's faces as the statement's dropped both suites. A
            # halted face halted before either suite ran: it carries the
            # record of where the condition halted (``halts_recorded``), onto
            # which the block composition splices what ran before the ``if``.
            return halts_recorded(cond, halt_record(ctx)).sequence(
                lambda value: self._select_on_face(value, ctx)
            )
        condition = plain_completed_value(cond)
        if condition is None:
            return cond
        return self._desugar_condition(condition, ctx)

    def _select_on_face(self, value, ctx):
        """One completed condition face selects its suites.

        A face whose truth is not one value (a guarded raise folded into its
        truth) keeps the face's own value, as every condition face did before
        faces selected suites: that gap is the truth law's, not this one's.
        """
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
        )

        if plain_completed_value(value.truth(self.site)) is None:
            return ExitSet.completed(value)
        return self._desugar_condition(value, ctx)

    def _ground_branch_result(self, ctx, observed_formula) -> None:
        """A ground condition decides this if's branch-result slot."""
        from sugar_lift_py_tests.outcome.exit_set import true_guard

        if ctx is None or self.branch_slot is None:
            return
        table = getattr(ctx, "ground_branch_results", None)
        if not isinstance(table, dict):
            return
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        table[self.branch_slot.slot_id] = (
            TrueBoolLiteralSugar(site=self.site)
            if observed_formula == true_guard()
            else FalseBoolLiteralSugar(site=self.site)
        )

    def _desugar_condition(self, condition, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.branch_result_coordinate import (
            BranchResultAuthentication,
            branch_result_guard,
        )
        from sugar_lift_py_tests.floor.guarded_faces import GuardedFaces
        from sugar_lift_py_tests.outcome import Completed, Halted
        from sugar_lift_py_tests.outcome.exit_set import partition as _partition
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        # Branches carry facts/effects: the guard is the condition's TRUTHINESS
        # as a predicate. `.truth` is uniform -- a predicate condition (`if a ==
        # b`) stands as its own formula, a bare value (`if c`) emits the Python
        # `py.truthy(c)` relation. A ground bool (`if True:`) folds to a literal
        # with no formula and is not lifted yet -- LOUD, never guard by nothing.
        # A condition expression that raised never gets here: its halted arm
        # is handed back before any branch is selected.
        observed_formula = predicate_formula(condition, self.site)
        from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard

        formula = (
            observed_formula
            if observed_formula in (false_guard(), true_guard())
            else branch_result_guard(self.branch_slot, self.site)
        )
        authentication = BranchResultAuthentication(
            self.branch_slot, observed_formula, self.site
        )

        # Carry the call-frame temporal into each branch. Formals are
        # BindingCoordinateRefSugar keyed by coordinate cid; without ctx the
        # branch suite cannot resolve authenticated actuals and panics as
        # unspecialized source-call formal (dual-mode EffectBoundary factories
        # nest further ifs that read those formals).
        # A ground condition selects one suite before that suite is reduced.
        # Reducing the dead peer first can demand a loud producer that Python
        # never executes, turning an unreachable diagnostic into a function
        # construction failure. Symbolic conditions still reduce both suites
        # and preserve their guarded exits exactly as before.
        # Walrus (and any FloorValue with non-identity extend_scope) binds
        # before branch selection — Python makes the name visible in BOTH arms.
        # Default FloorValue.extend_scope is identity.
        branch_ctx = condition.extend_scope(ctx)

        if observed_formula in (false_guard(), true_guard()):
            selected = reduce_block_to_exitset(
                self.then_body if observed_formula == true_guard() else self.else_body,
                branch_ctx,
            )
            self._ground_branch_result(ctx, observed_formula)
            if isinstance(selected, ExitSet) and not _is_linear(selected):
                # A ground condition selects ONE suite: the if is that suite.
                # Its faces are handed back as they are -- each with its own
                # temporal record -- never flattened into one completed face
                # whose entries are merely guarded.  Flattening put a store
                # made only after a call completed beside a completed face
                # under ``true``, so the constructor forked an impossible
                # companion that completed WITHOUT the store where the call
                # in fact raised.
                return selected
            then_exits, else_exits = (
                (selected, ExitSet(()))
                if observed_formula == true_guard()
                else (ExitSet(()), selected)
            )
        else:
            then_exits = reduce_block_to_exitset(self.then_body, branch_ctx)
            else_exits = reduce_block_to_exitset(self.else_body, branch_ctx)

        # If is union in the exit algebra: each branch is restricted to its
        # polarity, then the partitions normalize together. In particular, a
        # halt on one face coexists with the complementary Completed exit.
        # A selected ground-false else arm is the true face, not the merely
        # equivalent ``not(not(true))`` spelling.  Do not unwrap symbolic
        # branch guards: their internal negation is part of their identity.
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome.exit_set import complement_guard

        not_formula = (
            complement_guard(formula) if formula == false_guard() else not_(formula)
        )
        # This If OWNS the split, so it mints the partition and stamps each
        # branch with its face. Downstream factoring reads the exclusion off
        # the arms as testimony instead of re-proving it from guard spelling,
        # which stops being legible once these guards are conjoined with a
        # prefix or merged with a sibling arm.
        then_face, else_face = _partition(("IfSugar", self.site, formula))
        join = functools.partial(
            self._join_branches,
            formula=formula,
            not_formula=not_formula,
            then_face=then_face,
            else_face=else_face,
            observed_formula=observed_formula,
            authentication=authentication,
            # The context before the condition, not ``branch_ctx``: a walrus
            # in the test bound its evaluation into ``branch_ctx``, so every
            # arm holds it and it is carried out of the if like an arm's own.
            incoming=ctx,
        )
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )

        then_deferred = isinstance(then_exits, NativeOperationExitCarrierV1)
        else_deferred = isinstance(else_exits, NativeOperationExitCarrierV1)
        if then_deferred and else_deferred:
            # Both suites hold a formal native operation (``b = 1 // x`` /
            # ``b = 2 // x``). Each suite's exits exist only once caller
            # actuals discharge its own demand. The join waits for both: the
            # then carrier's discharge hands its faces to a step that returns
            # the else carrier, which the same discharge (the same caller
            # actuals) resolves before the ordinary union runs. Neither demand
            # is merged into the other and neither suite is decided early.
            return then_exits.after_discharge(
                lambda then_discharged: else_exits.after_discharge(
                    lambda else_discharged: join(then_discharged, else_discharged)
                )
            )
        if then_deferred ^ else_deferred:
            # One suite holds a formal native operation (``message =
            # exc.message`` evaluated at its assignment): its exits exist only
            # once caller actuals discharge it. The join waits for that
            # discharge and then is the ordinary union -- the deferred suite's
            # faces under its polarity, the decided peer under the other.
            if then_deferred:
                return then_exits.after_discharge(
                    lambda discharged: join(discharged, else_exits)
                )
            return else_exits.after_discharge(
                lambda discharged: join(then_exits, discharged)
            )
        return join(then_exits, else_exits)

    def _join_branches(
        self,
        then_exits,
        else_exits,
        *,
        formula,
        not_formula,
        then_face,
        else_face,
        observed_formula,
        authentication,
        incoming=None,
    ) -> ExitSet:
        from dataclasses import replace as _replace

        from sugar_lift_py_tests.floor.guarded_faces import GuardedFaces
        from sugar_lift_py_tests.outcome import Completed, Halted
        from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard
        from sugar_lift_py_tests.sugar.function_universe_sugar import face_record

        exits = then_exits.guarded(formula, then_face).union(
            else_exits.guarded(not_formula, else_face)
        )
        # A ground condition never uses the branch-result slot as the arm
        # guard (formula is already true_guard/false_guard). Authenticating
        # that unused slot would inject BranchResultAuthentication into every
        # folded `if not args:` factory prefix, and prefix CIDs cannot project
        # that testimony. Symbolic splits still publish the slot authentication.
        unconditional_entries = (
            ()
            if observed_formula in (false_guard(), true_guard())
            else (authentication,)
        )

        entries = []
        for exit_ in exits.exits:
            if isinstance(exit_, Completed):
                entries.extend(
                    entry.guarded(exit_.guard) for entry in exit_.value.entries
                )

        def falls_through(branch_exits):
            return any(
                isinstance(exit_, Completed) and exit_.value.can_fall_through
                for exit_ in branch_exits.exits
            )

        def only_halts(branch_exits):
            # A suite whose every exit is a halt sets no continuation guard:
            # its halts are arms of their own, and the completed face's arm
            # guard already excludes them.
            return bool(branch_exits.exits) and all(
                isinstance(exit_, Halted) for exit_ in branch_exits.exits
            )

        then_branch_exits = not falls_through(then_exits)
        else_branch_exits = not falls_through(else_exits)
        can_fall_through = not (then_branch_exits and else_branch_exits)
        # The tail rides under the polarity of whichever branch did NOT exit; if
        # both fall through it is unconditional, if both exit it is unreachable.
        continuation_guard = None
        if (
            then_branch_exits
            and not else_branch_exits
            and not only_halts(then_exits)
        ):
            continuation_guard = not_formula
        elif (
            else_branch_exits
            and not then_branch_exits
            and not only_halts(else_exits)
        ):
            continuation_guard = formula

        faces = GuardedFaces(
            guard=formula,
            entries=tuple(entries),
            then_exits=then_branch_exits,
            else_exits=else_branch_exits,
            can_fall_through=can_fall_through,
            continuation_guard=continuation_guard,
            unconditional_entries=unconditional_entries,
            # Each suite's arms under its polarity: a key's value on each
            # path is read under that path's own guard.
            evaluations=_arm_evaluations((exits,), incoming),
        )
        if not exits.halts() and not exits.owed_items():
            return ExitSet.completed(faces)

        def halted_after_condition(halt):
            # A halt in either suite stays a halted arm of the if (#7826): no
            # completed record holds a halt.  The condition's own testimony
            # (the branch-result slot's authentication) was established
            # before either suite ran, so the halted arm's record carries it
            # ahead of what the suite reached before halting. Every suite
            # halt carries the record its block composition gave it; one
            # with no record is stopped by name (``face_record``), never
            # given one made up with no context.
            inner = face_record(halt, owner="IfSugar.suite", blame=self.site)
            return ExitSet.halted(
                halt.effect,
                state=_replace(
                    inner, entries=(*unconditional_entries, *inner.entries)
                ),
            )

        # Every completed arm of both suites continues as the one completed
        # face; ``normalize``'s join merges those continuations into one arm
        # under the disjunction of their guards, owing every debt of the arms
        # it stands for. Each halt continues as itself over the condition's
        # testimony. Both compose through ``ExitSet.sequence``, so no guard,
        # face or ``owed`` is restated by hand.
        return exits.sequence(
            lambda _suite: ExitSet.completed(faces), consume=halted_after_condition
        )
