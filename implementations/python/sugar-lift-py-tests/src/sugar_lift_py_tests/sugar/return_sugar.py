from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.floor import ReturnValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class ReturnSugar(Sugar):
    """The `return <expr>` statement. Reduce the value; the result is a
    ReturnValue carrying that reduced floor. The block carries it as an exit,
    and the universe's post projects `out == <return term>` from it.

    Meaning-only, node-constructed. Bare `return` (no value) is not this sugar
    -- the tree node keeps it a gap rather than inventing a None return.
    """

    value: object  # the returned expression's sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n    return z\n\n"
        return _call_pair(
            name="return_value",
            owner_sugar="ReturnSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.value.desugar(ctx).and_then(
            lambda value: Complete(ReturnValue(value))
        )
