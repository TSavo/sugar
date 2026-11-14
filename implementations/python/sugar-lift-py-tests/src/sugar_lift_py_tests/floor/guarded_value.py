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
        return self._map("answer", ctx)

    def length(self, site):
        """Distribute length through both authenticated guarded arms."""
        return self._map("length", site)

    def _map(self, method: str, *args, **keywords):
        """Distribute ``method`` over both arms.

        ``keywords`` carries a binary operator's or an attribute read's ``ctx``
        to each arm, so an arm that applies a body applies it under the
        caller's context.
        """
        from sugar_lift_py_tests.floor.single_outcome_law import require_single_value
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import ExitSet

        owner = f"GuardedValue._map({method})"
        blame = args[-1] if args else method
        if args and isinstance(args[0], GuardedValue):
            other, *rest = args
            true_outcome = self._map(method, other.when_true, *rest, **keywords)
            if true_outcome.halts() == true_outcome.exits:
                return true_outcome.guarded(other.guard)
            false_outcome = self._map(method, other.when_false, *rest, **keywords)
            if false_outcome.halts() == false_outcome.exits:
                return false_outcome.guarded(not_(other.guard))
            true_outcome = require_single_value(
                true_outcome, owner=owner, blame=blame, arm="when_true"
            )
            false_outcome = require_single_value(
                false_outcome, owner=owner, blame=blame, arm="when_false"
            )
            # Rebuilt through ``sequence``: the joined arm owes what both owed.
            return true_outcome.sequence(
                lambda true_value: false_outcome.sequence(
                    lambda false_value: ExitSet.completed(
                        GuardedValue(other.guard, true_value, false_value)
                    )
                )
            )

        true_outcome = getattr(self.when_true, method)(*args, **keywords)
        if true_outcome.halts() == true_outcome.exits:
            return true_outcome.guarded(self.guard)
        false_outcome = getattr(self.when_false, method)(*args, **keywords)
        if false_outcome.halts() == false_outcome.exits:
            return false_outcome.guarded(not_(self.guard))
        # Dual-edge partitions from undecided native dispatch (BinOp/Compare):
        # weaken each arm's faces under the branch guard and union.  Joining two
        # partitions into one GuardedValue arm is not honest; the exit algebra
        # already carries both completion and halt faces.
        if (
            true_outcome.completed_value() is None
            or false_outcome.completed_value() is None
        ):
            return true_outcome.guarded(self.guard).union(
                false_outcome.guarded(not_(self.guard))
            )
        true_outcome = require_single_value(
            true_outcome, owner=owner, blame=blame, arm="when_true"
        )
        false_outcome = require_single_value(
            false_outcome, owner=owner, blame=blame, arm="when_false"
        )
        # Rebuilt through ``sequence``: the joined arm owes what both owed.
        return true_outcome.sequence(
            lambda true_value: false_outcome.sequence(
                lambda false_value: ExitSet.completed(
                    GuardedValue(self.guard, true_value, false_value)
                )
            )
        )

    def _predicate(self, method: str, *args, **keywords):
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

        owner = f"GuardedValue._predicate({method})"
        blame = args[-1] if args else method
        true_outcome = getattr(self.when_true, method)(*args, **keywords)
        if true_outcome.halts() == true_outcome.exits:
            return true_outcome.guarded(self.guard)
        false_outcome = getattr(self.when_false, method)(*args, **keywords)
        if false_outcome.halts() == false_outcome.exits:
            return false_outcome.guarded(not_(self.guard))
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
            return super().equals(args[0], args[-1], keywords.get("ctx"))
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
            args[-1],
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
        return self.predicate_from_left("less_than", left, site, ctx=ctx)

    def predicate_from_left(self, method: str, left, site, **keywords):
        """Distribute a binary predicate whose guarded value is the RHS."""
        return GuardedValue(
            self.guard, self.when_true, self.when_false
        )._predicate_from_left(method, left, site, **keywords)

    def map_from_left(self, method: str, left, site, ctx):
        """Distribute a binary value operation whose guarded value is the RHS,
        each arm under the caller's context."""
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import ExitSet

        from sugar_lift_py_tests.floor.single_outcome_law import require_single_value

        owner = f"GuardedValue.map_from_left({method})"
        true_outcome = getattr(left, method)(self.when_true, site, ctx)
        if true_outcome.halts() == true_outcome.exits:
            return true_outcome.guarded(self.guard)
        false_outcome = getattr(left, method)(self.when_false, site, ctx)
        if false_outcome.halts() == false_outcome.exits:
            return false_outcome.guarded(not_(self.guard))

        if (
            true_outcome.completed_value() is None
            or false_outcome.completed_value() is None
        ):
            from sugar_lift_py_tests.outcome.exit_set import partition

            true_face, false_face = partition(
                ("GuardedValue.map_from_left", str(site), method, self.guard)
            )
            return true_outcome.guarded(self.guard, true_face).union(
                false_outcome.guarded(not_(self.guard), false_face)
            )
        true_outcome = require_single_value(
            true_outcome, owner=owner, blame=site, arm="when_true"
        )
        false_outcome = require_single_value(
            false_outcome, owner=owner, blame=site, arm="when_false"
        )
        # Rebuilt through ``sequence``: the joined arm owes what both owed.
        return true_outcome.sequence(
            lambda true_value: false_outcome.sequence(
                lambda false_value: ExitSet.completed(
                    GuardedValue(self.guard, true_value, false_value)
                )
            )
        )

    def _predicate_from_left(self, method: str, left, site, **keywords):
        true_outcome = getattr(left, method)(self.when_true, site, **keywords)
        if true_outcome.halts() == true_outcome.exits:
            return true_outcome.guarded(self.guard)
        false_outcome = getattr(left, method)(self.when_false, site, **keywords)
        if false_outcome.halts() == false_outcome.exits:
            from sugar_lift_py_tests.ir import not_

            return false_outcome.guarded(not_(self.guard))
        from sugar_lift_py_tests.floor.single_outcome_law import require_single_value

        owner = f"GuardedValue._predicate_from_left({method})"
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
                )._predicate("truth", site)
            )
        )

    def subscript(self, index, site):
        return self._map("subscript", index, site)

    def subscript_with_occurrence(self, index, site, occurrence):
        """Distribute one authenticated Subscript occurrence to both arms."""
        return self._map("subscript_with_occurrence", index, site, occurrence)

    def attribute(self, name, site, ctx):
        """Distribute attribute projection over both branch faces.

        Pass-3 / full-dump desugar panics rank ``attribute`` second only to
        ``contains``; observed receiver is almost always GuardedValue (197 of
        229). The arms own what ``.name`` means; this face only threads the
        existing guard and the reading caller's context.
        """
        return self._map("attribute", name, site, ctx=ctx)

    def contains(self, item, site):
        """Distribute membership over both branch faces as a joined predicate."""
        return self._predicate("contains", item, site)

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
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import ExitSet

        owner = "GuardedValue.project_sequence_with"
        blame = operation.blame
        true_outcome = self.when_true.project_sequence_with(operation, ctx)
        false_outcome = self.when_false.project_sequence_with(operation, ctx)
        if true_outcome.completed_value() is None or (
            false_outcome.completed_value() is None
        ):
            return true_outcome.guarded(self.guard).union(
                false_outcome.guarded(not_(self.guard))
            )
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
        return self._map("setitem", index, value, site, ctx=ctx)

    def delitem(self, index, site, ctx):
        """Rebind both statically known receiver faces after a subscript delete."""
        return self._map("delitem", index, site, ctx=ctx)

    def add(self, other, site, ctx):
        return self._map("add", other, site, ctx=ctx)

    def append_with(self, value, site):
        if all(
            _stands_on_append_floor(face) for face in (self.when_true, self.when_false)
        ):
            return self._map("append_with", value, site)
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
        return self._map("subtract", other, site, ctx=ctx)

    def multiply(self, other, site, ctx):
        return self._map("multiply", other, site, ctx=ctx)

    def power(self, other, site, ctx):
        return self._map("power", other, site, ctx=ctx)

    def divide(self, other, site, ctx):
        return self._map("divide", other, site, ctx=ctx)

    def modulo(self, other, site, ctx):
        return self._map("modulo", other, site, ctx=ctx)

    def floor_divide(self, other, site, ctx):
        return self._map("floor_divide", other, site, ctx=ctx)

    def left_shift(self, other, site, ctx):
        return self._map("left_shift", other, site, ctx=ctx)

    def right_shift(self, other, site, ctx):
        return self._map("right_shift", other, site, ctx=ctx)

    def bitwise_or(self, other, site, ctx):
        return self._map("bitwise_or", other, site, ctx=ctx)

    def bitwise_invert(self, site):
        return self._map("bitwise_invert", site)

    def unary_minus(self, site):
        return self._map("unary_minus", site)

    def absolute(self, site):
        return self._map("absolute", site)

    def truth(self, site):
        return self._predicate("truth", site)

    def equals(self, other, site, ctx):
        return self._predicate("equals", other, site, ctx=ctx)

    def is_identical(self, other, site):  # type: ignore[override]
        return self._predicate("is_identical", other, site)

    def less_than(self, other, site, ctx):
        return self._predicate("less_than", other, site, ctx=ctx)

    def python_isinstance(self, type_name: str, type_term, site):
        return self._predicate("python_isinstance", type_name, type_term, site)

    def test_python_type(self, value, site):
        """Distribute an ``isinstance`` test over guarded type coordinates."""
        return self._predicate("test_python_type", value, site)

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
