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

The guard here is written from the pure-meaning primitives: `reduce_statements`
(block reduction), `entry.guarded(formula)` (implication), and the `GuardedFaces`
floor value the block reducer already consumes.
"""

from __future__ import annotations

import functools

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
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
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard

    truth = value.truth(site)
    if not isinstance(truth, Complete):
        raise NotImplementedError(
            f"condition truth did not produce one value: {type(truth).__name__}"
        )
    truth_value = truth.value
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
    )


@dataclass(frozen=True)
class BranchSuiteWithV1:
    """A ``with`` statement of a branch suite, constructed when its suite is.

    A ``with`` constructs only through the require door: its manager's
    contract must already be derived for its exact coordinate, or
    construction is refused.  A suite a ground condition never selects is
    never reduced (``_desugar_condition``), so Python never enters that
    ``with``; demanding its manager contract while constructing the ``if``
    turned an unreachable refusal into the whole function's
    (``pandas.io.common._get_binary_io_classes``: ``with
    zstd.ZstdDecompressor().stream_reader(b"")`` under ``if zstd is not
    None`` where ``zstd`` is ``None`` because zstandard is not installed;
    #7665).  The ``with`` is constructed -- by the same door, with the same
    refusal -- exactly when its suite is reduced: under a symbolic condition
    both suites still reduce and a refused ``with`` still refuses.
    """

    node: object

    def force(self):
        return self.node.sugar()


def construct_definition_branch_withs(root) -> None:
    """Construct every ``with`` a definition's branch suites carry (#7699).

    ``BranchSuiteWithV1`` defers a ``with`` until its suite is reduced, and a
    reduction decides which suite is reached.  Accounting a definition
    (``roll_call.discharge``) constructs it and reduces nothing, so no suite
    of it is ever selected and a deferred ``with`` was never demanded: the
    definition answered clean while its ``with`` was never built
    (``pandas/plotting/_matplotlib/__init__.py:67``, ``with
    plt.rc_context():`` under ``if ax is None and len(...) > 0``).  A
    definition's suite is reachable unless a reduction proves it dead, and
    none was made here, so each deferred ``with`` of the definition is
    constructed now -- by the same require door, refused by the same named
    ``With`` refusal when its manager has no contract.

    Only the definition's own sugar tree is walked: a nested definition is
    its own root, and a callee's suites belong to the call that reduces them.
    """
    from dataclasses import fields, is_dataclass

    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        FunctionUniverseSugar,
    )

    seen: set[int] = set()

    def visit(value, *, top: bool = False) -> None:
        if id(value) in seen:
            return
        seen.add(id(value))
        if type(value) is BranchSuiteWithV1:
            visit(value.force())
            return
        if isinstance(value, (tuple, list)):
            for item in value:
                visit(item)
            return
        if not isinstance(value, Sugar) or not is_dataclass(value):
            return
        if isinstance(value, FunctionUniverseSugar) and not top:
            return
        for spec in fields(value):
            visit(getattr(value, spec.name, None))

    visit(root, top=True)


def _constructed_suite(body: tuple) -> tuple:
    return tuple(
        statement.force() if type(statement) is BranchSuiteWithV1 else statement
        for statement in body
    )


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
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )

        cond = self.test.desugar(ctx)
        if isinstance(cond, NativeOperationExitCarrierV1):
            return cond.and_then(lambda value: self._desugar_condition(value, ctx))
        from sugar_lift_py_tests.outcome import ExitSet, Halted

        if isinstance(cond, ExitSet) and any(
            isinstance(face, Halted) for face in cond.exits
        ):
            # A condition that may raise (an unknown callee completes or
            # raises): each completed face selects its suites under its own
            # guard; a halted face never reaches either suite. Returning the
            # condition's faces as the statement's dropped both suites.
            return NativeOperationExitCarrierV1.compose_prefix(
                cond, lambda value: self._select_on_face(value, ctx)
            )
        if not isinstance(cond, Complete):
            return cond
        return self._desugar_condition(cond.value, ctx)

    def _select_on_face(self, value, ctx):
        """One completed condition face selects its suites.

        A face whose truth is not one value (a guarded raise folded into its
        truth) keeps the face's own value, as every condition face did before
        faces selected suites: that gap is the truth law's, not this one's.
        """
        if not isinstance(value.truth(self.site), Complete):
            return Complete(value)
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

    def _desugar_condition(self, condition, ctx: object = None) -> Outcome:
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
        # A condition expression that raised never gets here: it is an
        # ``Incomplete``, handed back before any branch is selected.
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
        from sugar_lift_py_tests.outcome import ExitSet

        # Walrus (and any FloorValue with non-identity extend_scope) binds
        # before branch selection — Python makes the name visible in BOTH arms.
        # Default FloorValue.extend_scope is identity.
        branch_ctx = condition.extend_scope(ctx)

        if observed_formula in (false_guard(), true_guard()):
            selected = reduce_block_to_exitset(
                _constructed_suite(
                    self.then_body
                    if observed_formula == true_guard()
                    else self.else_body
                ),
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
            then_exits = reduce_block_to_exitset(
                _constructed_suite(self.then_body), branch_ctx
            )
            else_exits = reduce_block_to_exitset(
                _constructed_suite(self.else_body), branch_ctx
            )

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
    ) -> Outcome:
        from sugar_lift_py_tests.floor.guarded_faces import GuardedFaces
        from sugar_lift_py_tests.outcome import Completed, Halted, Incomplete
        from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard

        exits = then_exits.guarded(formula, then_face).union(
            else_exits.guarded(not_formula, else_face)
        )
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
                unconditional_entries=unconditional_entries,
            )
        )
