from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula

from .floor_value import FloorValue


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

    def _map(self, method: str, *args):
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        if args and isinstance(args[0], GuardedValue):
            other, *rest = args
            true_outcome = self._map(method, other.when_true, *rest)
            if isinstance(true_outcome, Incomplete):
                return true_outcome.guarded(other.guard)
            false_outcome = self._map(method, other.when_false, *rest)
            if isinstance(false_outcome, Incomplete):
                return false_outcome.guarded(not_(other.guard))
            return Complete(
                GuardedValue(other.guard, true_outcome.value, false_outcome.value)
            )

        from sugar_lift_py_tests.floor.single_outcome_law import (
            pending_demand,
            require_single_value,
            rewrap_pending,
        )

        owner = f"GuardedValue._map({method})"
        blame = args[-1] if args else method
        true_outcome = getattr(self.when_true, method)(*args)
        if isinstance(true_outcome, Incomplete):
            return true_outcome.guarded(self.guard)
        false_outcome = getattr(self.when_false, method)(*args)
        if isinstance(false_outcome, Incomplete):
            return false_outcome.guarded(not_(self.guard))
        # An arm may answer with a value that still owes a parameter contract
        # (`(a if c else p)[i]` for a formal `p`). The demand is owed only on that
        # arm's face; hoist it, join the carried values, then re-attach it.
        true_pending, true_outcome = pending_demand(true_outcome, self.guard)
        false_pending, false_outcome = pending_demand(false_outcome, not_(self.guard))
        true_outcome = require_single_value(
            true_outcome, owner=owner, blame=blame, arm="when_true"
        )
        false_outcome = require_single_value(
            false_outcome, owner=owner, blame=blame, arm="when_false"
        )
        joined = Complete(
            GuardedValue(self.guard, true_outcome.value, false_outcome.value)
        )
        joined = rewrap_pending(true_pending, joined, owner=owner, blame=blame)
        return rewrap_pending(false_pending, joined, owner=owner, blame=blame)

    def _predicate(self, method: str, *args):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import and_, implies, not_
        from sugar_lift_py_tests.outcome import Complete, Incomplete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        from sugar_lift_py_tests.floor.single_outcome_law import (
            pending_demand,
            require_single_value,
            rewrap_pending,
        )

        owner = f"GuardedValue._predicate({method})"
        blame = args[-1] if args else method
        true_outcome = getattr(self.when_true, method)(*args)
        if isinstance(true_outcome, Incomplete):
            return true_outcome.guarded(self.guard)
        false_outcome = getattr(self.when_false, method)(*args)
        if isinstance(false_outcome, Incomplete):
            return false_outcome.guarded(not_(self.guard))
        true_pending, true_outcome = pending_demand(true_outcome, self.guard)
        false_pending, false_outcome = pending_demand(false_outcome, not_(self.guard))
        true_outcome = require_single_value(
            true_outcome, owner=owner, blame=blame, arm="when_true"
        )
        false_outcome = require_single_value(
            false_outcome, owner=owner, blame=blame, arm="when_false"
        )

        def _rejoin(outcome):
            outcome = rewrap_pending(true_pending, outcome, owner=owner, blame=blame)
            return rewrap_pending(false_pending, outcome, owner=owner, blame=blame)

        true_value = true_outcome.value
        false_value = false_outcome.value

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
            return _rejoin(super().equals(args[0], args[-1]))
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
        joined = Complete(
            PredicateValue(
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
        )
        return _rejoin(joined)

    def predicate_from_left(self, method: str, left, site):
        """Distribute a binary predicate whose guarded value is the RHS."""
        return GuardedValue(
            self.guard, self.when_true, self.when_false
        )._predicate_from_left(method, left, site)

    def map_from_left(self, method: str, left, site):
        """Distribute a binary value operation whose guarded value is the RHS."""
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        from sugar_lift_py_tests.floor.single_outcome_law import (
            pending_demand,
            require_single_value,
            rewrap_pending,
        )

        owner = f"GuardedValue.map_from_left({method})"
        true_outcome = getattr(left, method)(self.when_true, site)
        if isinstance(true_outcome, Incomplete):
            return true_outcome.guarded(self.guard)
        false_outcome = getattr(left, method)(self.when_false, site)
        if isinstance(false_outcome, Incomplete):
            return false_outcome.guarded(not_(self.guard))
        true_pending, true_outcome = pending_demand(true_outcome, self.guard)
        false_pending, false_outcome = pending_demand(false_outcome, not_(self.guard))
        true_outcome = require_single_value(
            true_outcome, owner=owner, blame=site, arm="when_true"
        )
        false_outcome = require_single_value(
            false_outcome, owner=owner, blame=site, arm="when_false"
        )
        joined = Complete(
            GuardedValue(self.guard, true_outcome.value, false_outcome.value)
        )
        joined = rewrap_pending(true_pending, joined, owner=owner, blame=site)
        return rewrap_pending(false_pending, joined, owner=owner, blame=site)

    def _predicate_from_left(self, method: str, left, site):
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        true_outcome = getattr(left, method)(self.when_true, site)
        if isinstance(true_outcome, Incomplete):
            return true_outcome.guarded(self.guard)
        false_outcome = getattr(left, method)(self.when_false, site)
        if isinstance(false_outcome, Incomplete):
            from sugar_lift_py_tests.ir import not_

            return false_outcome.guarded(not_(self.guard))
        from sugar_lift_py_tests.floor.single_outcome_law import (
            pending_demand,
            require_single_value,
            rewrap_pending,
        )
        from sugar_lift_py_tests.ir import not_

        owner = f"GuardedValue._predicate_from_left({method})"
        true_pending, true_outcome = pending_demand(true_outcome, self.guard)
        false_pending, false_outcome = pending_demand(false_outcome, not_(self.guard))
        true_outcome = require_single_value(
            true_outcome, owner=owner, blame=site, arm="when_true"
        )
        false_outcome = require_single_value(
            false_outcome, owner=owner, blame=site, arm="when_false"
        )
        joined = GuardedValue(self.guard, true_outcome.value, false_outcome.value)
        outcome = joined._predicate("truth", site)
        outcome = rewrap_pending(true_pending, outcome, owner=owner, blame=site)
        return rewrap_pending(false_pending, outcome, owner=owner, blame=site)

    def subscript(self, index, site):
        return self._map("subscript", index, site)

    def attribute(self, name, site):
        """Distribute attribute projection over both branch faces.

        Pass-3 / full-dump desugar panics rank ``attribute`` second only to
        ``contains``; observed receiver is almost always GuardedValue (197 of
        229). The arms own what ``.name`` means; this face only threads the
        existing guard.
        """
        return self._map("attribute", name, site)

    def contains(self, item, site):
        """Distribute membership over both branch faces as a joined predicate."""
        return self._predicate("contains", item, site)

    def setitem(self, index, value, site):
        """Rebind both statically known receiver faces after a subscript store."""
        return self._map("setitem", index, value, site)

    def delitem(self, index, site):
        """Rebind both statically known receiver faces after a subscript delete."""
        return self._map("delitem", index, site)

    def add(self, other, site):
        return self._map("add", other, site)

    def append_with(self, value, site):
        if all(
            "append_with" in type(face).__dict__
            for face in (self.when_true, self.when_false)
        ):
            return self._map("append_with", value, site)
        from sugar_lift_py_tests.effect import (
            AppendRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            AppendRuntimeEffect(
                "append runtime boundary: guarded receiver has a branch without "
                f"a constructed list post-state; value={value.to_term(owner=str(site))!r}; "
                f"site={site}",
                **runtime_effect_evidence("py.append", self, site),
            )
        )

    def subtract(self, other, site):
        return self._map("subtract", other, site)

    def multiply(self, other, site):
        return self._map("multiply", other, site)

    def power(self, other, site):
        return self._map("power", other, site)

    def divide(self, other, site):
        return self._map("divide", other, site)

    def modulo(self, other, site):
        return self._map("modulo", other, site)

    def floor_divide(self, other, site):
        return self._map("floor_divide", other, site)

    def left_shift(self, other, site):
        return self._map("left_shift", other, site)

    def right_shift(self, other, site):
        return self._map("right_shift", other, site)

    def bitwise_or(self, other, site):
        return self._map("bitwise_or", other, site)

    def bitwise_invert(self, site):
        return self._map("bitwise_invert", site)

    def unary_minus(self, site):
        return self._map("unary_minus", site)

    def absolute(self, site):
        return self._map("absolute", site)

    def truth(self, site):
        return self._predicate("truth", site)

    def equals(self, other, site):
        return self._predicate("equals", other, site)

    def is_identical(self, other, site):  # type: ignore[override]
        return self._predicate("is_identical", other, site)

    def less_than(self, other, site):
        return self._predicate("less_than", other, site)

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
