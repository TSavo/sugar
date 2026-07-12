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

    def _map(self, method: str, *args):
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        true_outcome = getattr(self.when_true, method)(*args)
        if isinstance(true_outcome, Incomplete):
            return true_outcome.guarded(self.guard)
        false_outcome = getattr(self.when_false, method)(*args)
        if isinstance(false_outcome, Incomplete):
            return false_outcome.guarded(not_(self.guard))
        assert isinstance(true_outcome, Complete)
        assert isinstance(false_outcome, Complete)
        return Complete(
            GuardedValue(self.guard, true_outcome.value, false_outcome.value)
        )

    def _predicate(self, method: str, *args):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import and_, implies, not_
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        true_outcome = getattr(self.when_true, method)(*args)
        if isinstance(true_outcome, Incomplete):
            return true_outcome.guarded(self.guard)
        false_outcome = getattr(self.when_false, method)(*args)
        if isinstance(false_outcome, Incomplete):
            return false_outcome.guarded(not_(self.guard))
        assert isinstance(true_outcome, Complete)
        assert isinstance(false_outcome, Complete)
        true_value = true_outcome.value
        false_value = false_outcome.value
        if not isinstance(true_value, PredicateValue) or not isinstance(
            false_value, PredicateValue
        ):
            return super().equals(args[0], args[-1])
        return Complete(
            PredicateValue(
                and_(
                    [
                        implies(self.guard, true_value.formula),
                        implies(not_(self.guard), false_value.formula),
                    ]
                ),
                args[-1],
                operand_callsites=(
                    *true_value.operand_callsites,
                    *false_value.operand_callsites,
                ),
            )
        )

    def subscript(self, index, site):
        return self._map("subscript", index, site)

    def add(self, other, site):
        return self._map("add", other, site)

    def equals(self, other, site):
        return self._predicate("equals", other, site)

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
