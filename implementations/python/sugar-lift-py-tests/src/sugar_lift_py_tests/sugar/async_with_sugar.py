from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ObjectValue, ScopeRebind
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


class AsyncContextManagerOperation: pass
class BindValueOperation: pass


@dataclass(frozen=True)
class AsyncWithSugar(Sugar, role=SugarRole.STATEMENT):
    manager: SugarBody
    body: SugarBody
    optional_name: str | None
    site: object = field(compare=False)

    @classmethod
    def owns(cls, site): return site.observed == "AsyncWith" and site.with_item_count() == 1 and (site.with_optional_vars_observed() is None or site.with_optional_vars_name() is not None)

    @classmethod
    def new(cls, site, ctx): return cls(ctx.build_body(site.with_context_expr(), SugarRole.TERM), ctx.build_body(site.with_body(), SugarRole.STATEMENT), site.with_optional_vars_name(), site)

    @classmethod
    def witnesses(cls):
        prefix = "async def A(z):\n    async with z as x:\n        return x\n\n"
        return _call_pair(name="async_with_dunder", owner_sugar=cls.__name__, truthful=prefix+"def test_a():\n    assert 1 == 1\n", lying=prefix+"def test_a():\n    assert 1 == 2\n")

    def desugar(self, ctx=None) -> Outcome:
        return self.manager.reduce(ctx).and_then(lambda manager: self._finish(manager, ctx))

    def _finish(self, manager, ctx):
        if not isinstance(manager, ObjectValue):
            return manager._floor_gap(owner=type(self).__name__, blame=str(self.site), observed=type(manager).__name__, requested="async context manager data-model methods", fix="construct __aenter__ and __aexit__")
        ctx.record_operation(owner="AsyncWithSugar", method_name="async_context_manager_with", operation=AsyncContextManagerOperation())
        entered = manager.call_method_value("__aenter__", (), owner=type(self).__name__, blame=str(self.site), ctx=ctx).value
        entered = force_floor(entered, ctx, owner="AsyncWithSugar.__aenter__")
        body_ctx = ctx
        if self.optional_name is not None:
            ctx.record_operation(owner="AsyncWithSugar", method_name="bind_with", operation=BindValueOperation())
            body_ctx = ScopeRebind(self.optional_name, entered).extend_scope(ctx)
        outcome = self.body.reduce(body_ctx)
        exit_call = manager.call_method_value("__aexit__", (entered, entered, entered), owner=type(self).__name__, blame=str(self.site), ctx=ctx).value
        force_floor(exit_call, ctx, owner="AsyncWithSugar.__aexit__")
        return outcome

    def walk_children(self): return (self.manager, self.body)
