from __future__ import annotations

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


class RaiseSugar(Sugar, role=SugarRole.STATEMENT):
    """`raise ...` -- a statement that IS an effect.

    It produces no value and warrants no constraint: it transfers control out of the
    function, so every statement after it is unreachable. That is exactly an Incomplete
    effect, so desugar is one line: `return Incomplete(RaiseEffect)`. The block reducing
    it matches the Incomplete and bubbles it upward, doing no work past it -- the same
    short-circuit as any other effect (division by zero, etc.). No reduction, no
    detection: the sugar simply is the Incomplete.
    """

    @classmethod
    def owns(cls, fragment) -> bool:
        return fragment.observed == "Raise"

    @classmethod
    def build(cls, fragment, ctx) -> "RaiseSugar":
        if fragment.observed != "Raise":
            raise TypeError("RaiseSugar claim built a non-raise statement")
        return cls()

    def desugar(self, ctx=None) -> Outcome:
        return Incomplete(
            "raise: a runtime effect that transfers control and halts "
            "constraint propagation (every statement after it is unreachable)"
        )
