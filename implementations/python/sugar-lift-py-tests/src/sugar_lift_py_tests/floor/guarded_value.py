from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula

from .floor_value import FloorValue


def _require_rebind_roster(value, *, owner: str, blame, arm: str):
    """An arm's unpack answer as a rebind roster, or a NAMED construction gap.

    ``require_single_value`` proves the arm answered with ONE value; it does not
    prove that value is a ``ScopeRebinds``. Reading ``.bindings`` off whatever
    came back would be a bare ``AttributeError`` -- the unnamed-assertion shape
    ``single_outcome_law`` exists to eliminate, and it would name neither the
    law nor the arm that broke it.
    """
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds

    if isinstance(value, ScopeRebinds):
        return value.bindings
    from sugar_lift_py_tests.gap.info import GapKind
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner=owner,
        blame=blame,
        observed=(
            f"the {arm} arm's unpack answered with {type(value).__name__}, "
            "which carries no target rebinds to join"
        ),
        requested="a ScopeRebinds roster from every arm of a guarded unpack",
        fix=(
            "give that floor's project_sequence_with a ScopeRebinds answer, or "
            "leave it a loud gap; never join a roster that is not one"
        ),
        gap_kind=GapKind.FLOOR,
    )


def _stands_on_append_floor(face) -> bool:
    """Whether ``face`` answers ``append_with`` itself.

    Its class must define ``append_with``; a class whose instances differ
    (``OpaqueOpCallsite``: only the ``STR_SPLIT`` coordinate is list-shaped)
    narrows it by ``stands_on_append_floor``.
    """
    if "append_with" not in type(face).__dict__:
        return False
    narrowed = getattr(face, "stands_on_append_floor", None)
    return narrowed() if callable(narrowed) else True


def _deferred(outcome) -> bool:
    """Whether an arm's operation still waits on its caller's actual: a
    parameter arm answered through its operation's door with the carrier."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    return isinstance(outcome, NativeOperationExitCarrierV1)


def _all_halt(outcome) -> bool:
    """Every arm of an answered outcome halts (a carrier has not answered)."""
    return not _deferred(outcome) and outcome.halts() == outcome.exits


def _beside(guard, true_outcome, false_outcome):
    """Both arms' outcomes, each under its own polarity, when either arm's
    operation still waits on its caller (#7757).

    The two polarities are composed through ``ExitSet.sequence``, which hands
    a carrier on through its own ``after_discharge``: once the caller's
    actual answers, that arm's exits land beneath its guard, beside every
    exit of the other arm.  Neither arm's exits are dropped for the other's.
    """
    from sugar_lift_py_tests.ir import not_
    from sugar_lift_py_tests.outcome import ExitSet

    polarities = ExitSet.completed(True, guard).union(
        ExitSet.completed(False, not_(guard))
    )
    return polarities.sequence(lambda taken: true_outcome if taken else false_outcome)


def _siblings(guard, true_outcome, false_outcome, faces=(None, None)):
    """Both arms' outcomes as siblings: each under its own polarity (``guard``
    and its negation), joined by the one sibling join (``ExitSet.union``).

    A halt is never dropped (#7757, #7827 item 1): an arm whose exits all
    halt keeps them under its guard, beside every exit of the other arm --
    its completions and its own halts.  ``faces`` is the pair of partition
    faces the caller owns for the two polarities, when it owns one.
    """
    from sugar_lift_py_tests.ir import not_

    true_face, false_face = faces
    return true_outcome.guarded(guard, true_face).union(
        false_outcome.guarded(not_(guard), false_face)
    )


def _joined(guard, true_outcome, false_outcome, *, owner: str, blame):
    """Two single-valued arms rejoined as one ``GuardedValue`` under ``guard``,
    rebuilt through ``sequence``: the joined arm owes what both owed."""
    from sugar_lift_py_tests.floor.single_outcome_law import require_single_value
    from sugar_lift_py_tests.outcome import ExitSet

    true_outcome = require_single_value(
        true_outcome, owner=owner, blame=blame, arm="when_true"
    )
    false_outcome = require_single_value(
        false_outcome, owner=owner, blame=blame, arm="when_false"
    )
    return true_outcome.sequence(
        lambda true_value: false_outcome.sequence(
            lambda false_value: ExitSet.completed(
                GuardedValue(guard, true_value, false_value)
            )
        )
    )


@dataclass(frozen=True)
class GuardedValue(FloorValue):
    """A definitely-bound value selected by an existing branch guard.

    This is not an ite term. Operations distribute into both arms, and boolean
    results rejoin through the same implication formulas GuardedFaces uses.
    """

    guard: Formula
    when_true: FloorValue
    when_false: FloorValue

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, formula_term

        return ctor(
            "py.conditional",
            [
                formula_term(self.guard),
                self.when_true.to_term(owner=owner),
                self.when_false.to_term(owner=owner),
            ],
        )

    def answer(self, ctx=None):
        """Resolve both binding arms when a joined name is read."""
        return self._map(lambda arm: arm.answer(ctx), operation="answer", blame=ctx)

    def length(self, site):
        """Distribute length through both authenticated guarded arms."""
        return self._map(lambda arm: arm.length(site), operation="length", blame=site)

    def _map(self, operate, *, operation: str, blame):
        """Distribute one operation over both arms.

        ``operate(arm)`` is that operation's explicit call on one arm, through
        the operation's one door (``discharge_subscript`` for a read,
        ``AttributeSugar.project_attribute`` for an attribute, the floor's own
        method for the rest), never a method looked up by its name (#7757).
        It carries a binary operator's or an attribute read's ``ctx`` to each
        arm, so an arm that applies a body applies it under the caller's
        context.  ``operation`` only names the operation in a refusal.

        An arm whose operation waits on its caller (a parameter arm, answered
        with the carrier) keeps both arms' outcomes, each under its own
        polarity (:func:`_beside`).  Both arms are always evaluated: an arm
        that halts on every exit is a sibling of the other arm, never a
        reason to skip it (:func:`_siblings`).
        """
        owner = f"GuardedValue._map({operation})"
        true_outcome = operate(self.when_true)
        false_outcome = operate(self.when_false)
        if _deferred(true_outcome) or _deferred(false_outcome):
            return _beside(self.guard, true_outcome, false_outcome)
        # An arm that halts, or a dual-edge partition from undecided native
        # dispatch (BinOp/Compare): each arm's faces under its own polarity,
        # unioned.  Joining two partitions into one GuardedValue arm is not
        # honest; the exit algebra already carries both completion and halt
        # faces.
        if (
            true_outcome.completed_value() is None
            or false_outcome.completed_value() is None
        ):
            return _siblings(self.guard, true_outcome, false_outcome)
        return _joined(
            self.guard, true_outcome, false_outcome, owner=owner, blame=blame
        )

    def _map_over(self, operand, operate, *, operation: str, blame):
        """Distribute ``operate(arm, operand)`` over both arms, a guarded
        ``operand`` split first: each of its arms meets both of this value's
        arms, and the results rejoin under the operand's own guard.  Both of
        the operand's arms are always evaluated (:func:`_siblings`)."""
        if not isinstance(operand, GuardedValue):
            return self._map(
                lambda arm: operate(arm, operand), operation=operation, blame=blame
            )
        owner = f"GuardedValue._map({operation})"
        true_outcome = self._map_over(
            operand.when_true, operate, operation=operation, blame=blame
        )
        false_outcome = self._map_over(
            operand.when_false, operate, operation=operation, blame=blame
        )
        if _deferred(true_outcome) or _deferred(false_outcome):
            return _beside(operand.guard, true_outcome, false_outcome)
        if _all_halt(true_outcome) or _all_halt(false_outcome):
            return _siblings(operand.guard, true_outcome, false_outcome)
        return _joined(
            operand.guard, true_outcome, false_outcome, owner=owner, blame=blame
        )

    def _predicate(self, operate, *, operation: str, operand, blame, ctx=None):
        """Distribute one predicate over both arms and rejoin its formulas.

        ``operate(arm)`` is the predicate's explicit call on one arm (#7757);
        ``operand`` is the predicate's first operand, which an arm answering
        no formula is compared to (``FloorValue.equals``).
        """
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import and_, implies, not_
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        from sugar_lift_py_tests.floor.single_outcome_law import require_single_value

        owner = f"GuardedValue._predicate({operation})"
        true_outcome = operate(self.when_true)
        false_outcome = operate(self.when_false)
        if _deferred(true_outcome) or _deferred(false_outcome):
            return _beside(self.guard, true_outcome, false_outcome)
        if _all_halt(true_outcome) or _all_halt(false_outcome):
            return _siblings(self.guard, true_outcome, false_outcome)
        true_outcome = require_single_value(
            true_outcome, owner=owner, blame=blame, arm="when_true"
        )
        false_outcome = require_single_value(
            false_outcome, owner=owner, blame=blame, arm="when_false"
        )

        true_value = true_outcome.completed_value()
        false_value = false_outcome.completed_value()

        def formula(value):
            if isinstance(value, PredicateValue):
                return value.formula
            if type(value) is TrueBoolLiteralSugar:
                return and_([])
            if type(value) is FalseBoolLiteralSugar:
                return not_(and_([]))
            return None

        true_formula = formula(true_value)
        false_formula = formula(false_value)
        if true_formula is None or false_formula is None:
            return super().equals(operand, blame, ctx)
        if (
            type(true_value) is TrueBoolLiteralSugar
            and type(false_value) is FalseBoolLiteralSugar
        ):
            joined_formula = self.guard
        elif (
            type(true_value) is FalseBoolLiteralSugar
            and type(false_value) is TrueBoolLiteralSugar
        ):
            joined_formula = not_(self.guard)
        else:
            joined_formula = and_(
                [
                    implies(self.guard, true_formula),
                    implies(not_(self.guard), false_formula),
                ]
            )
        joined = PredicateValue(
            joined_formula,
            blame,
            operand_callsites=(
                *(
                    true_value.operand_callsites
                    if isinstance(true_value, PredicateValue)
                    else ()
                ),
                *(
                    false_value.operand_callsites
                    if isinstance(false_value, PredicateValue)
                    else ()
                ),
            ),
        )
        # Both arms' predicates ran: the joined arm is sequenced after both,
        # so it owes what both owed (#7825, H4), exactly as ``_map`` rejoins.
        return true_outcome.sequence(
            lambda _true_value: false_outcome.sequence(
                lambda _false_value: ExitSet.completed(joined)
            )
        )

    def less_than_from_left(self, left, site, ctx):
        """Typed Floor obligation: distribute ``left <`` across guarded arms.

        Preserves existing guarded-predicate distribution; does not invent a
        generic getattr/string surface on the Floor protocol.
        """
        return self.predicate_from_left(
            lambda arm: left.less_than(arm, site, ctx), site, operation="less_than"
        )

    def predicate_from_left(self, operate, site, *, operation: str):
        """Distribute a binary predicate whose guarded value is the RHS.

        ``operate(arm)`` is the left operand's explicit predicate call on one
        arm (#7757); ``operation`` only names it in a refusal.  Both arms are
        always evaluated (:func:`_siblings`).
        """
        true_outcome = operate(self.when_true)
        false_outcome = operate(self.when_false)
        if _deferred(true_outcome) or _deferred(false_outcome):
            return _beside(self.guard, true_outcome, false_outcome)
        if _all_halt(true_outcome) or _all_halt(false_outcome):
            return _siblings(self.guard, true_outcome, false_outcome)
        from sugar_lift_py_tests.floor.single_outcome_law import require_single_value

        owner = f"GuardedValue._predicate_from_left({operation})"
        true_outcome = require_single_value(
            true_outcome, owner=owner, blame=site, arm="when_true"
        )
        false_outcome = require_single_value(
            false_outcome, owner=owner, blame=site, arm="when_false"
        )
        # Rebuilt through ``sequence``: the joined predicate owes what both
        # arms owed.
        return true_outcome.sequence(
            lambda true_value: false_outcome.sequence(
                lambda false_value: GuardedValue(
                    self.guard, true_value, false_value
                ).truth(site)
            )
        )

    def map_from_left(self, operate, site, *, operation: str):
        """Distribute a binary value operation whose guarded value is the RHS.

        ``operate(arm)`` is the left operand's explicit call of the operation
        on one arm, under the caller's context (#7757); ``operation`` names
        the operation in a refusal and in the partition it owns.  Both arms
        are always evaluated: an arm that halts is a sibling of the other
        (:func:`_siblings`).
        """
        owner = f"GuardedValue.map_from_left({operation})"
        true_outcome = operate(self.when_true)
        false_outcome = operate(self.when_false)
        if _deferred(true_outcome) or _deferred(false_outcome):
            return _beside(self.guard, true_outcome, false_outcome)
        if (
            true_outcome.completed_value() is None
            or false_outcome.completed_value() is None
        ):
            from sugar_lift_py_tests.outcome.exit_set import partition

            return _siblings(
                self.guard,
                true_outcome,
                false_outcome,
                partition(
                    ("GuardedValue.map_from_left", str(site), operation, self.guard)
                ),
            )
        return _joined(self.guard, true_outcome, false_outcome, owner=owner, blame=site)

    def subscript_with(self, operation, ctx):
        """``guarded[index]``: each arm is read through the one subscript door
        (``discharge_subscript``), under the reading caller's context, so a
        parameter arm defers its read to the caller (#7757).  A guarded index
        is split first."""
        from sugar_lift_py_tests.operations.subscript_operation import (
            discharge_subscript,
        )

        return self._map_over(
            operation.index,
            lambda arm, index: discharge_subscript(
                arm,
                index,
                operation.blame,
                ctx,
                owner=operation.owner,
                use_occurrence=operation.use_occurrence,
            ),
            operation="subscript",
            blame=operation.blame,
        )

    def subscript_with_occurrence(self, index, site, occurrence):
        """Distribute one authenticated Subscript occurrence to both arms,
        through :meth:`subscript_with`."""
        from sugar_lift_py_tests.operations.subscript_operation import (
            SubscriptOperation,
        )

        return self.subscript_with(
            SubscriptOperation(
                index=index,
                owner="GuardedValue.subscript",
                blame=site,
                use_occurrence=occurrence,
            ),
            None,
        )

    def attribute(self, name, site, ctx):
        """Distribute attribute projection over both branch faces.

        Pass-3 / full-dump desugar panics rank ``attribute`` second only to
        ``contains``; observed receiver is almost always GuardedValue (197 of
        229). The arms own what ``.name`` means; this face only threads the
        existing guard and the reading caller's context.  Each arm is read
        through the one attribute door (``AttributeSugar.project_attribute``),
        so a parameter arm defers its read to the caller (#7757).
        """
        from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar

        return self._map(
            lambda arm: AttributeSugar.project_attribute(arm, name, site, ctx),
            operation="attribute",
            blame=site,
        )

    def contains(self, item, site):
        """Distribute membership over both branch faces as a joined predicate."""
        return self._predicate(
            lambda arm: arm.contains(item, site),
            operation="contains",
            operand=item,
            blame=site,
        )

    def project_sequence_with(self, operation, ctx):
        """Unpack a guarded right-hand side: distribute, rejoin PER TARGET NAME.

        ``a, b = (x if c else y)`` binds ``a`` to the join of the two arms'
        FIRST members and ``b`` to the join of their seconds. It does not
        produce one ``GuardedValue`` wrapping two whole ``ScopeRebinds``: that
        shape stops the panic but binds nothing a later statement can read,
        because scope threading walks ``ScopeRebinds.bindings``.

        ``_map`` cannot carry this. Every other distribution here rejoins two
        VALUES, and this operation's arms answer with a rebind roster, so the
        join has to happen one layer in. What is shared with ``_map`` is the
        conventions, and they are kept: an arm answering with an effect keeps
        its own guard polarity, and an arm's own decidable arity mismatch stays
        loud rather than being laundered by distributing.

        Both rosters come from ``operation.target_names``, so they agree by
        construction; ``strict=True`` states that rather than assuming it.

        An arm that does not answer one completed roster (it halts, or it is
        a runtime unpack with both faces) keeps every one of its exits under
        its own polarity, beside every exit of the other arm: neither arm's
        halt nor its completion is dropped for the other's.
        """
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
        from sugar_lift_py_tests.outcome import ExitSet

        owner = "GuardedValue.project_sequence_with"
        blame = operation.blame
        true_outcome = self.when_true.project_sequence_with(operation, ctx)
        false_outcome = self.when_false.project_sequence_with(operation, ctx)
        if true_outcome.completed_value() is None or (
            false_outcome.completed_value() is None
        ):
            return _siblings(self.guard, true_outcome, false_outcome)
        true_bindings = _require_rebind_roster(
            true_outcome.completed_value(), owner=owner, blame=blame, arm="when_true"
        )
        false_bindings = _require_rebind_roster(
            false_outcome.completed_value(),
            owner=owner,
            blame=blame,
            arm="when_false",
        )
        joined = ScopeRebinds(
            tuple(
                (name, GuardedValue(self.guard, true_member, false_member))
                for (name, true_member), (_, false_member) in zip(
                    true_bindings, false_bindings, strict=True
                )
            )
        )
        # Rebuilt through ``sequence``: the joined roster owes what both owed.
        return true_outcome.sequence(
            lambda _true: false_outcome.sequence(
                lambda _false: ExitSet.completed(joined)
            )
        )

    def setitem(self, index, value, site, ctx):
        """Rebind both statically known receiver faces after a subscript store."""
        return self._map_over(
            index,
            lambda arm, index: arm.setitem(index, value, site, ctx),
            operation="setitem",
            blame=site,
        )

    def delitem(self, index, site, ctx):
        """Rebind both statically known receiver faces after a subscript delete."""
        return self._map_over(
            index,
            lambda arm, index: arm.delitem(index, site, ctx),
            operation="delitem",
            blame=site,
        )

    def add(self, other, site, ctx):
        return self._map_over(
            other,
            lambda arm, other: arm.add(other, site, ctx),
            operation="add",
            blame=site,
        )

    def append_with(self, value, site):
        if all(
            _stands_on_append_floor(face) for face in (self.when_true, self.when_false)
        ):
            return self._map_over(
                value,
                lambda arm, value: arm.append_with(value, site),
                operation="append_with",
                blame=site,
            )
        from sugar_lift_py_tests.effect import (
            AppendRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.halted(
            AppendRuntimeEffect(
                "append runtime boundary: guarded receiver has a branch without "
                f"a constructed list post-state; value={value.to_term(owner=str(site))!r}; "
                f"site={site}",
                **runtime_effect_evidence("py.append", self, site),
            )
        )

    def subtract(self, other, site, ctx):
        return self._map_over(
            other,
            lambda arm, other: arm.subtract(other, site, ctx),
            operation="subtract",
            blame=site,
        )

    def multiply(self, other, site, ctx):
        return self._map_over(
            other,
            lambda arm, other: arm.multiply(other, site, ctx),
            operation="multiply",
            blame=site,
        )

    def power(self, other, site, ctx):
        return self._map_over(
            other,
            lambda arm, other: arm.power(other, site, ctx),
            operation="power",
            blame=site,
        )

    def divide(self, other, site, ctx):
        return self._map_over(
            other,
            lambda arm, other: arm.divide(other, site, ctx),
            operation="divide",
            blame=site,
        )

    def modulo(self, other, site, ctx):
        return self._map_over(
            other,
            lambda arm, other: arm.modulo(other, site, ctx),
            operation="modulo",
            blame=site,
        )

    def floor_divide(self, other, site, ctx):
        return self._map_over(
            other,
            lambda arm, other: arm.floor_divide(other, site, ctx),
            operation="floor_divide",
            blame=site,
        )

    def left_shift(self, other, site, ctx):
        return self._map_over(
            other,
            lambda arm, other: arm.left_shift(other, site, ctx),
            operation="left_shift",
            blame=site,
        )

    def right_shift(self, other, site, ctx):
        return self._map_over(
            other,
            lambda arm, other: arm.right_shift(other, site, ctx),
            operation="right_shift",
            blame=site,
        )

    def bitwise_or(self, other, site, ctx):
        return self._map_over(
            other,
            lambda arm, other: arm.bitwise_or(other, site, ctx),
            operation="bitwise_or",
            blame=site,
        )

    def bitwise_invert(self, site):
        return self._map(
            lambda arm: arm.bitwise_invert(site), operation="bitwise_invert", blame=site
        )

    def unary_minus(self, site):
        return self._map(
            lambda arm: arm.unary_minus(site), operation="unary_minus", blame=site
        )

    def truth(self, site):
        return self._predicate(
            lambda arm: arm.truth(site), operation="truth", operand=site, blame=site
        )

    def equals(self, other, site, ctx):
        return self._predicate(
            lambda arm: arm.equals(other, site, ctx),
            operation="equals",
            operand=other,
            blame=site,
            ctx=ctx,
        )

    def is_identical(self, other, site):  # type: ignore[override]
        return self._predicate(
            lambda arm: arm.is_identical(other, site),
            operation="is_identical",
            operand=other,
            blame=site,
        )

    def less_than(self, other, site, ctx):
        return self._predicate(
            lambda arm: arm.less_than(other, site, ctx),
            operation="less_than",
            operand=other,
            blame=site,
            ctx=ctx,
        )

    def python_isinstance(self, type_name: str, type_term, site):
        return self._predicate(
            lambda arm: arm.python_isinstance(type_name, type_term, site),
            operation="python_isinstance",
            operand=type_name,
            blame=site,
        )

    def test_python_type(self, value, site):
        """Distribute an ``isinstance`` test over guarded type coordinates."""
        return self._predicate(
            lambda arm: arm.test_python_type(value, site),
            operation="test_python_type",
            operand=value,
            blame=site,
        )

    def callsites(self):
        return (*self.when_true.callsites(), *self.when_false.callsites())

    def post_formula(self, out):
        from sugar_lift_py_tests.ir import and_, eq, implies, not_

        def branch(value):
            if isinstance(value, GuardedValue):
                return value.post_formula(out)
            return eq(out, value.to_term(owner="guarded post"))

        return and_(
            [
                implies(self.guard, branch(self.when_true)),
                implies(not_(self.guard), branch(self.when_false)),
            ]
        )
