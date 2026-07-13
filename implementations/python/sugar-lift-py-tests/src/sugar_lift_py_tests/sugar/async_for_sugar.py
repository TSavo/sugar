from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import factory_panic_gap
from sugar_lift_py_tests.floor import ObjectValue
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


class AsyncIteratorOperation:
    pass


class AsyncNextOperation:
    pass


@dataclass(frozen=True)
class AsyncForSugar(Sugar, role=SugarRole.STATEMENT):
    iterable: SugarBody
    body: SugarBody
    target_name: str
    site: object = field(compare=False)

    @classmethod
    def owns(cls, site):
        return (
            site.observed == "AsyncFor"
            and site.for_orelse_count() == 0
            and site.for_target_name() is not None
        )

    @classmethod
    def new(cls, site, ctx):
        return cls(
            ctx.build_body(site.for_iter(), SugarRole.TERM),
            ctx.build_body(site.for_body_block(), SugarRole.STATEMENT),
            site.for_target_name(),
            site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "async def A(z):\n    async for x in z:\n        return x\n\n"
        return _call_pair(
            name="async_for_dunder",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert 1 == 1\n",
            lying=prefix + "def test_a():\n    assert 1 == 2\n",
        )

    def desugar(self, ctx=None) -> Outcome:
        return self.iterable.reduce(ctx).and_then(
            lambda value: self._finish(value, ctx)
        )

    def _finish(self, value, ctx):
        if not isinstance(value, ObjectValue):
            return value._floor_gap(
                owner=type(self).__name__,
                blame=str(self.site),
                observed=type(value).__name__,
                requested="async iterator data-model method",
                fix="construct __aiter__",
            )
        ctx.record_operation(
            owner="AsyncForSugar",
            method_name="async_iter_with",
            operation=AsyncIteratorOperation(),
        )
        value.call_method_value(
            "__aiter__", (), owner=type(self).__name__, blame=str(self.site), ctx=ctx
        )
        ctx.record_operation(
            owner="AsyncForSugar.__aiter__",
            method_name="async_next_with",
            operation=AsyncNextOperation(),
        )
        value.call_method_value(
            "__anext__", (), owner=type(self).__name__, blame=str(self.site), ctx=ctx
        )
        factory_panic_gap(
            owner=type(self).__name__,
            blame=str(self.site),
            observed="AsyncFor.__anext__",
            requested="async iteration stop floor",
            fix="construct StopAsyncIteration termination",
        )

    def walk_children(self):
        return (self.iterable, self.body)
