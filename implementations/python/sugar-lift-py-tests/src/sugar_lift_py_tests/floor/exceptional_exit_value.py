from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import RaiseEffect

from .floor_value import FloorValue


@dataclass(frozen=True)
class ExceptionalExitValue(FloorValue):
    """A reduced raise projected into a return-selection branch.

    This is control-flow testimony, not a Python exception instance and not a
    RuntimeEffect. Its term is the same source-cited exceptional-exit
    coordinate emitted by ``RaiseValue`` and ``GuardedRaise`` posts.
    """

    effect: RaiseEffect

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.floor.raise_value import _exceptional_exit_term

        return _exceptional_exit_term(self.effect)

    def add(self, other, site):
        """Keep a selected exceptional path halted across addition."""
        del other, site
        from sugar_lift_py_tests.outcome import Complete

        return Complete(self)

    def subtract(self, other, site):
        """Keep a selected exceptional path halted across subtraction.

        Python never evaluates the arithmetic result after the left operand
        has already raised. ``ExceptionalExitValue`` is that reduced
        control-flow testimony, so subtraction preserves it exactly rather
        than manufacturing a numeric value or runtime effect.
        """
        del other, site
        from sugar_lift_py_tests.outcome import Complete

        return Complete(self)

    def multiply(self, other, site):
        """Keep a selected exceptional path halted across multiplication.

        Python never evaluates the product after the left operand has already
        raised. Preserve the exact exceptional-exit testimony; this is neither
        a multiplication result nor a runtime-dependent effect.
        """
        del other, site
        from sugar_lift_py_tests.outcome import Complete

        return Complete(self)

    def divide(self, other, site):
        """Keep a selected exceptional path halted across division.

        Python never evaluates the quotient after the left operand has already
        raised. Preserve the exact exceptional-exit testimony; this is neither
        a division result nor a runtime-dependent effect.
        """
        del other, site
        from sugar_lift_py_tests.outcome import Complete

        return Complete(self)

    def floor_divide(self, other, site):
        """Keep a selected exceptional path halted across floor division."""
        del other, site
        from sugar_lift_py_tests.outcome import Complete

        return Complete(self)

    def subscript(self, index, site):
        """Keep a selected exceptional path halted across subscripting."""
        del index, site
        from sugar_lift_py_tests.outcome import Complete

        return Complete(self)
