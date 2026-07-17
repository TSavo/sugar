from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AwaitOperation:
    """Floor operation for ``await`` — call ≠ termination (#4688).

    Closed-static ObjectValue awaitables may force ``__await__`` without
    claiming an event-loop schedule. Symbolic/runtime awaitables stay typed
    red (``AwaitRuntimeEffect``). A bare async call never discharges the
    body result.
    """

    owner: str
    blame: str

    def await_object(self, receiver, ctx) -> Outcome:
        from sugar_lift_py_tests.floor.call_site_value import force_floor

        call = receiver.call_method_value(
            "__await__",
            (),
            owner=self.owner,
            blame=self.blame,
            ctx=ctx,
        )
        return call.and_then(
            lambda result: Complete(force_floor(result, ctx, owner="AwaitSugar result"))
        )


@dataclass(frozen=True)
class AwaitSugar(Sugar, role=SugarRole.TERM):
    """``await <awaitable>`` — data-model force of a completed awaitable.

    ADJUDICATION (#4688): witnessing an await is not the same as witnessing
    that an async callable terminated. ``async def F; F(...)`` constructs a
    coroutine; the body face is available only after termination drive.
    Until an AsyncFunctionDef universe + termination-gated callsite bridge
    exist, the enrolled witness is typed red over a symbolic awaitable
    (truthful matches the effect; lying mismatches). Never forge sat/unsat
    from a bare unrelated assert, and never treat ``F(x)`` as body result.
    """

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
        # Symbolic regime: free awaitable cannot be forced without a concrete
        # awaitable floor / event-loop witness. Discrimination is effect match.
        return typed_red_effect_witness(
            name="await_runtime_effect",
            owner_sugar=cls.__name__,
            source="async def A(z):\n    return await z\n",
            effect_class="AwaitRuntimeEffect",
            reason_needle="await runtime boundary",
            blame_needle="test_witness.py:2:11",
            wrong_reason_needle="owner=AsyncForSugar",
        )

    def desugar(self, ctx=None) -> Outcome:
        return self.awaitable.reduce(ctx).and_then(
            lambda value: self._finish(value, ctx)
        )

    def _finish(self, value, ctx):
        operation = AwaitOperation(
            owner=type(self).__name__,
            blame=self.site,
        )
        recorder = None if ctx is None else getattr(ctx, "record_operation", None)
        if recorder is not None:
            recorder(
                owner="AwaitSugar",
                method_name="await_with",
                operation=operation,
            )
        # Ask the floor: ObjectValue force_floor path; SymbolicValue typed red;
        # every other floor stays a loud construction gap. No silent default.
        return value.await_with(operation, ctx)

    def walk_children(self):
        return (self.awaitable,)
