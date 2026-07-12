from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class SubscriptSugar(Sugar, role=SugarRole.TERM):
    """`x[i]` subscript. Reduce the receiver and the index, and ask the receiver
    to subscript by the index. Concrete containers fold; out-of-range / missing
    key is a named runtime effect; symbolic sides stay the py.subscript
    coordinate. Slice indexes remain behind the narrower
    ``SliceSubscriptSugar`` gate; ``SliceSugar`` owns the Slice node without
    widening this parent's receiver evaluation semantics."""

    receiver: SugarBody
    index: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Subscript":
            return False
        index = site.subscript_index()
        if index.observed == "Slice":
            return False
        if index.observed == "Tuple" and any(
            element.observed == "Slice" for element in index.tuple_elts()
        ):
            return False
        return True

    @classmethod
    def new(cls, site, ctx) -> "SubscriptSugar":
        # Receiver and index are factory-built (audited), never reduced here.
        return cls(
            receiver=ctx.build_body(site.subscript_receiver(), SugarRole.TERM),
            index=ctx.build_body(site.subscript_index(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Concrete list index folds: truthful rides 20, lying asserts 21.
        prefix = "def A(z):\n    xs = [10, 20, 30]\n    return xs[1]\n\n"
        return _call_pair(
            name="subscript_return",
            owner_sugar="SubscriptSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 20\n",
            lying=prefix + "def test_a():\n    assert A(5) == 21\n",
        )

    def desugar(self, ctx: Any = None) -> Outcome:
        # Reduce receiver, reduce index, ask the receiver to subscript by the index.
        return self.receiver.reduce(ctx).and_then(
            lambda receiver: self.index.reduce(ctx).and_then(
                lambda index: self._subscript(receiver, index, ctx)
            )
        )

    def _subscript(self, receiver, index, ctx):
        from sugar_lift_py_tests.floor import CallSiteValue, ObjectValue
        from sugar_lift_py_tests.floor.call_site_value import force_floor

        recorder = getattr(ctx, "record_operation", None)
        if recorder is not None:
            class SubscriptOperation:
                pass
            recorder(
                owner="StringSubscriptSugar",
                method_name="subscript_with",
                operation=SubscriptOperation(),
            )
        if isinstance(index, CallSiteValue):
            index = force_floor(index, ctx, owner="SubscriptSugar index")
        if isinstance(receiver, ObjectValue):
            return receiver.call_method_value(
                "__getitem__",
                (index,),
                owner=type(self).__name__,
                blame=str(self.site),
                ctx=ctx,
            )
        return receiver.subscript(index, self.site)

    def walk_children(self):
        return (self.receiver, self.index)
