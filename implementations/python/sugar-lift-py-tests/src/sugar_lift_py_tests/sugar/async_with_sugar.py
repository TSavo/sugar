from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ObjectValue, ScopeRebind
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AsyncContextManagerOperation:
    """Floor operation for ``async with`` — call ≠ termination (#4688)."""

    owner: str
    blame: str

    def async_context_object(self, receiver, ctx) -> Outcome:
        """Closed-static ObjectValue managers force ``__aenter__``/``__aexit__``.

        Body threading is owned by AsyncWithSugar; this method only proves the
        manager dunder surface exists. Symbolic managers never reach here —
        they stay typed red on the floor.
        """
        del ctx
        return receiver.call_method_value(
            "__aenter__",
            (),
            owner=self.owner,
            blame=self.blame,
            ctx=None,
        )


@dataclass(frozen=True)
class BindValueOperation:
    pass


@dataclass(frozen=True)
class AsyncWithSugar(Sugar, role=SugarRole.STATEMENT):
    """``async with <manager> as name: body`` — async context-manager surface.

    ADJUDICATION (#4688): async with is a suspension membrane. Symbolic
    managers are typed red (``AsyncContextManagerRuntimeEffect``). Closed
    static ObjectValue managers may force ``__aenter__``/``__aexit__`` without
    claiming scheduler interleaving. Enrolled witness is typed red over a
    free manager — not a forged sat/unsat pair, and not a bare unrelated
    assert. Sat/unsat discrimination waits on AsyncFunctionDef + termination
    drive (retirement path named by the factory: create async_function_def_sugar).
    """

    manager: SugarBody
    body: SugarBody
    optional_name: str | None
    site: object = field(compare=False)

    @classmethod
    def owns(cls, site):
        return (
            site.observed == "AsyncWith"
            and site.with_item_count() == 1
            and (
                site.with_optional_vars_observed() is None
                or site.with_optional_vars_name() is not None
            )
        )

    @classmethod
    def new(cls, site, ctx):
        return cls(
            ctx.build_body(site.with_context_expr(), SugarRole.TERM),
            ctx.build_body(site.with_body(), SugarRole.STATEMENT),
            site.with_optional_vars_name(),
            site,
        )

    @classmethod
    def witnesses(cls):
        return typed_red_effect_witness(
            name="async_with_runtime_effect",
            owner_sugar=cls.__name__,
            source=(
                "async def A(z):\n" "    async with z as x:\n" "        return x\n"
            ),
            effect_class="AsyncContextManagerRuntimeEffect",
            reason_needle="async with runtime boundary",
            blame_needle="test_witness.py:2:4",
            wrong_reason_needle="owner=AwaitSugar",
        )

    def desugar(self, ctx=None) -> Outcome:
        return self.manager.reduce(ctx).and_then(
            lambda manager: self._finish(manager, ctx)
        )

    def _finish(self, manager, ctx):
        operation = AsyncContextManagerOperation(
            owner=type(self).__name__,
            blame=self.site,
        )
        recorder = None if ctx is None else getattr(ctx, "record_operation", None)
        if recorder is not None:
            recorder(
                owner="AsyncWithSugar",
                method_name="async_context_manager_with",
                operation=operation,
            )
        if not isinstance(manager, ObjectValue):
            # Symbolic / non-object: floor typed red or loud construction gap.
            return manager.async_context_manager_with(operation, ctx)
        entered = manager.call_method_value(
            "__aenter__", (), owner=type(self).__name__, blame=self.site, ctx=ctx
        ).value
        entered = force_floor(entered, ctx, owner="AsyncWithSugar.__aenter__")
        body_ctx = ctx
        if self.optional_name is not None:
            if recorder is not None:
                recorder(
                    owner="AsyncWithSugar",
                    method_name="bind_with",
                    operation=BindValueOperation(),
                )
            body_ctx = ScopeRebind(self.optional_name, entered).extend_scope(ctx)
        outcome = self.body.reduce(body_ctx)
        exit_call = manager.call_method_value(
            "__aexit__",
            (entered, entered, entered),
            owner=type(self).__name__,
            blame=self.site,
            ctx=ctx,
        ).value
        force_floor(exit_call, ctx, owner="AsyncWithSugar.__aexit__")
        return outcome

    def walk_children(self):
        return (self.manager, self.body)
