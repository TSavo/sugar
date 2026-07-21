"""Attribute access `<receiver>.<name>`.

Reduce the receiver and ask it for the attribute -- the value owns what `.name`
means, exactly as SubscriptSugar asks the receiver what `[index]` means. A
symbolic receiver stays the opaque `py.getattr(recv, "name")` coordinate (the
same EUF vocabulary as `py.subscript`); a value that owns the field folds; a
value with no attribute floor hits its own loud gap. The attribute NAME is a
static identifier carried onto the coordinate, never desugared.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class AttributeSugar(Sugar):
    receiver: Sugar
    name: str
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # `z.numerator` on an int is z itself; the pair rides the coordinate's
        # identity vs a contradicting asserted value.
        prefix = "def A(z):\n    return z.numerator\n\n"
        return _call_pair(
            name="attribute_return",
            owner_sugar="AttributeSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: receiver.attribute(self.name, self.site)
        )
