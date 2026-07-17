from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import factory_panic_gap
from sugar_lift_py_tests.floor import ObjectValue
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AsyncIteratorOperation:
    """Floor operation for ``async for`` iter — call ≠ termination (#4688)."""

    owner: str
    blame: str

    def async_iter_object(self, receiver, ctx) -> Outcome:
        del ctx
        return receiver.call_method_value(
            "__aiter__",
            (),
            owner=self.owner,
            blame=self.blame,
            ctx=None,
        )


@dataclass(frozen=True)
class AsyncNextOperation:
    """Floor operation for ``async for`` next — stop floor still owed."""

    owner: str
    blame: str

    def async_next_object(self, receiver, ctx) -> Outcome:
        del ctx
        return receiver.call_method_value(
            "__anext__",
            (),
            owner=self.owner,
            blame=self.blame,
            ctx=None,
        )


@dataclass(frozen=True)
class AsyncForSugar(Sugar, role=SugarRole.STATEMENT):
    """``async for target in iterable: body`` — async iteration surface.

    ADJUDICATION (#4688): async for is a suspension membrane. Symbolic
    iterables are typed red (``AsyncIterationRuntimeEffect``). Closed static
    ObjectValue iterators force ``__aiter__``/``__anext__`` and stay loud at
    the StopAsyncIteration termination floor (never invent loop completion).
    Enrolled witness is typed red over a free iterable. Sat/unsat
    discrimination waits on AsyncFunctionDef + termination drive.
    """

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
        return typed_red_effect_witness(
            name="async_for_runtime_effect",
            owner_sugar=cls.__name__,
            source=("async def A(z):\n" "    async for x in z:\n" "        return x\n"),
            effect_class="AsyncIterationRuntimeEffect",
            reason_needle="async for runtime boundary",
            blame_needle="test_witness.py:2:4",
            wrong_reason_needle="owner=AwaitSugar",
        )

    def desugar(self, ctx=None) -> Outcome:
        return self.iterable.reduce(ctx).and_then(
            lambda value: self._finish(value, ctx)
        )

    def _finish(self, value, ctx):
        iter_op = AsyncIteratorOperation(
            owner=type(self).__name__,
            blame=str(self.site),
        )
        recorder = None if ctx is None else getattr(ctx, "record_operation", None)
        if recorder is not None:
            recorder(
                owner="AsyncForSugar",
                method_name="async_iter_with",
                operation=iter_op,
            )
        if not isinstance(value, ObjectValue):
            # Symbolic / non-object: floor typed red or loud construction gap.
            return value.async_iter_with(iter_op, ctx)
        value.call_method_value(
            "__aiter__", (), owner=type(self).__name__, blame=str(self.site), ctx=ctx
        )
        next_op = AsyncNextOperation(
            owner=type(self).__name__,
            blame=str(self.site),
        )
        if recorder is not None:
            recorder(
                owner="AsyncForSugar.__aiter__",
                method_name="async_next_with",
                operation=next_op,
            )
        value.call_method_value(
            "__anext__", (), owner=type(self).__name__, blame=str(self.site), ctx=ctx
        )
        # Termination of async iteration is not inventable: StopAsyncIteration
        # remains a loud named gap until a real stop floor owns it.
        factory_panic_gap(
            owner=type(self).__name__,
            blame=str(self.site),
            observed="AsyncFor.__anext__",
            requested="async iteration stop floor",
            fix="construct StopAsyncIteration termination",
        )

    def walk_children(self):
        return (self.iterable, self.body)
