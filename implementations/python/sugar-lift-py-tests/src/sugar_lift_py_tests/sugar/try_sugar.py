from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RaiseEffect, RuntimeEffect
from sugar_lift_py_tests.floor import BlockValue
from sugar_lift_py_tests.operations import (
    FinallyFallthroughOperation,
    RouteRaisesOperation,
    perform_operation,
)
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.try_handler import TryHandler
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TrySugar(Sugar, role=SugarRole.STATEMENT):
    body: SugarBody
    handlers: tuple[TryHandler, ...]
    else_body: SugarBody | None
    finally_body: SugarBody | None
    blame: str

    def __post_init__(self) -> None:
        if not isinstance(self.body, SugarBody):
            raise TypeError("TrySugar body must be factory-built")
        if self.else_body is not None and not isinstance(self.else_body, SugarBody):
            raise TypeError("TrySugar else body must be factory-built")
        if self.finally_body is not None and not isinstance(
            self.finally_body, SugarBody
        ):
            raise TypeError("TrySugar finally body must be factory-built")

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed in {"Try", "TryStar"}

    @classmethod
    def build(cls, site, ctx) -> "TrySugar":
        if site.observed not in {"Try", "TryStar"}:
            raise TypeError("TrySugar claim built a non-try statement")
        return cls(
            body=ctx.build_body(site.try_body(), SugarRole.STATEMENT),
            handlers=tuple(
                TryHandler(
                    exception_names=handler.except_handler_type_names(),
                    bound_name=handler.except_handler_name(),
                    body=ctx.build_body(
                        handler.except_handler_body(), SugarRole.STATEMENT
                    ),
                    blame=handler.blame,
                )
                for handler in site.try_handlers()
            ),
            else_body=_build_optional(site.try_orelse(), ctx),
            finally_body=_build_optional(site.try_finalbody(), ctx),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        exit_outcome = self._try_exit(ctx)
        if self.finally_body is None:
            return exit_outcome
        return _apply_finally(exit_outcome, self.finally_body, ctx, self.blame)

    def _try_exit(self, ctx) -> Outcome:
        outcome = self.body.reduce(ctx)
        if isinstance(outcome, Incomplete):
            return self._route_incomplete(outcome, ctx)
        block = complete_value(outcome, owner="try body")
        if not isinstance(block, BlockValue):
            raise TypeError("TrySugar body must reduce to a block")
        routed = perform_operation(
            owner="TrySugar",
            blame=self.blame,
            receiver=block,
            method_name="route_raises_with",
            operation=RouteRaisesOperation(
                self.handlers,
                owner="TrySugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )
        if isinstance(routed, Incomplete):
            return routed
        block = complete_value(routed, owner="try routed body")
        if not isinstance(block, BlockValue):
            raise TypeError("TrySugar routed body must reduce to a block")
        if self.else_body is not None and _runs_else(block):
            return self.else_body.reduce(ctx)
        return Complete(block)

    def _route_incomplete(self, outcome: Incomplete, ctx) -> Outcome:
        effect = outcome.effect
        if not isinstance(effect, RaiseEffect):
            return outcome
        for handler in self.handlers:
            if handler.matches(effect):
                return handler.reduce(ctx, effect)
        return outcome


def _build_optional(site, ctx) -> SugarBody | None:
    if site is None:
        return None
    return ctx.build_body(site, SugarRole.STATEMENT)


def _runs_else(block: BlockValue) -> bool:
    return not block.statements


def _apply_finally(
    incoming: Outcome, finally_body: SugarBody, ctx, blame: str
) -> Outcome:
    outcome = finally_body.reduce(ctx)
    if isinstance(outcome, Incomplete):
        return outcome
    final_block = complete_value(outcome, owner="try finally")
    if not isinstance(final_block, BlockValue):
        raise TypeError("TrySugar finally body must reduce to a block")
    if not final_block.statements:
        return incoming
    if not final_block.fall_through:
        return Complete(final_block)
    if isinstance(incoming, Incomplete):
        return Incomplete(
            RuntimeEffect(
                "finally guarded return over incomplete incoming exit: add guarded "
                "effect exit joining before lowering this TrySugar shape"
            )
        )
    incoming_block = complete_value(incoming, owner="try incoming exit")
    if not isinstance(incoming_block, BlockValue):
        raise TypeError("TrySugar incoming exit must reduce to a block")
    return perform_operation(
        owner="TrySugar.finally",
        blame=blame,
        receiver=final_block,
        method_name="merge_finally_with",
        operation=FinallyFallthroughOperation(
            incoming_block=incoming_block,
            owner="TrySugar.finally",
            blame=blame,
        ),
        ctx=ctx,
    )
