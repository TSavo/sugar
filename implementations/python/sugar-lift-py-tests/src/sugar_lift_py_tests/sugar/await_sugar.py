from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ObjectValue
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


class AwaitOperation:
    pass


@dataclass(frozen=True)
class AwaitSugar(Sugar, role=SugarRole.TERM):
    awaitable: SugarBody
    site: object = field(compare=False)

    @classmethod
    def owns(cls, site):
        return site.observed == "Await"

    @classmethod
    def new(cls, site, ctx):
        return cls(ctx.build_body(site.await_value(), SugarRole.TERM), site)

    @classmethod
    def witnesses(cls):
        prefix = "class A:\n    def __await__(self):\n        return 1\n\nasync def F():\n    return await A()\n\n"
        return _call_pair(
            name="await_dunder_return",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert 1 == 1\n",
            lying=prefix + "def test_a():\n    assert 1 == 2\n",
        )

    def desugar(self, ctx=None) -> Outcome:
        return self.awaitable.reduce(ctx).and_then(
            lambda value: self._finish(value, ctx)
        )

    def _finish(self, value, ctx):
        if not isinstance(value, ObjectValue):
            return value._floor_gap(
                owner=type(self).__name__,
                blame=str(self.site),
                observed=type(value).__name__,
                requested="await data-model method",
                fix="construct __await__",
            )
        ctx.record_operation(
            owner="AwaitSugar", method_name="await_with", operation=AwaitOperation()
        )
        call = value.call_method_value(
            "__await__", (), owner=type(self).__name__, blame=str(self.site), ctx=ctx
        )
        return call.and_then(
            lambda result: Complete(force_floor(result, ctx, owner="AwaitSugar result"))
        )

    def walk_children(self):
        return (self.awaitable,)
