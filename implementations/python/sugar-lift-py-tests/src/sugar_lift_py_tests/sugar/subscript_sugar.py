from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class SubscriptSugar(Sugar):
    """`<receiver>[<index>]`. Reduce the receiver and the index, then ask the
    receiver to subscript by the index -- the value owns what indexing means.
    Concrete containers fold (a string indexes to its character); a vendor
    object routes through its ``__getitem__``; decidable out-of-range indexes
    and missing keys stay loud until their exact exceptional exits are built;
    symbolic sides stand as the py.subscript coordinate.

    Meaning-only, node-constructed. Slice indexes are a narrower case (their
    own sugar): a Slice node here reduces to its own gap through the recursion,
    never silently handled by this parent.
    """

    receiver: Sugar
    index: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # The ground failing bounds check contributes exact exceptional-exit
        # testimony on one path; the continuing path gives the solver a
        # verdict-bearing truthful/lying pair.
        prefix = "def A(z):\n    if z < 0:\n        return [][0]\n    return z\n\n"
        return _call_pair(
            name="subscript_return",
            owner_sugar="SubscriptSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: Any = None) -> Outcome:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.index.desugar(ctx).and_then(
                lambda index: self._subscript(receiver, index, ctx)
            )
        )

    def _subscript(self, receiver, index, ctx):
        from sugar_lift_py_tests.floor import ObjectValue

        if isinstance(receiver, ObjectValue):
            return receiver.call_method_value(
                "__getitem__",
                (index,),
                owner=type(self).__name__,
                blame=self.site,
                ctx=ctx,
            )
        return receiver.subscript(index, self.site)
