from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NoReturn

from sugar_lift_py_tests.ir import Term
from sugar_lift_py_tests.sugar.function_body_universe import FunctionBodyUniverse
from sugar_lift_py_tests.sugar_body import SugarBody

from .floor_value import FloorValue

_FORCE_FLOOR_BUDGET = 64


@dataclass(frozen=True)
class CallSiteValue(FloorValue):
    """A callsite as two things at once.

    The `term` is the bridge/culture coordinate used by contract composition.
    The factory-built `body` is only reduced when a downstream floor demands a
    concrete value (for example, a list literal index).
    """

    target_name: str
    arg_values: tuple[FloorValue, ...]
    parameters: tuple[str, ...]
    term: Term
    body: SugarBody | FunctionBodyUniverse | None

    def to_term(self, *, owner: str):
        del owner
        return self.term

    def project_callsite_with(self, operation, ctx):
        return operation.project_callsite(self, ctx)

    def attribute_with(self, operation: Any, ctx: Any):
        del ctx
        from sugar_lift_py_tests.effect import RuntimeEffect
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            RuntimeEffect(
                "callsite attribute runtime boundary: "
                f"`{self.target_name}.{operation.name}` requires executing the "
                "call result before Python attribute lookup; keep as typed red "
                "until a narrower vendor-cited floor owns the call result and "
                f"attribute. blame={operation.blame}"
            )
        )

    def unary_operator_with(self, operation, ctx):
        from sugar_lift_py_tests.effect import RuntimeEffect
        from sugar_lift_py_tests.factory import FactoryGap
        from sugar_lift_py_tests.operations import perform_operation
        from sugar_lift_py_tests.outcome import Incomplete

        try:
            floor = force_floor(
                self,
                ctx,
                owner=f"{operation.owner} callsite unary operand",
                project_callsite=False,
            )
        except FactoryGap as exc:
            observed = str(exc.info.get("observed", "callsite floor unavailable"))
            return Incomplete(
                RuntimeEffect(
                    "unary operator runtime boundary: callsite value "
                    f"`{self.target_name}` cannot be reduced before applying "
                    f"`{operation.operator}`. Python evaluates the call result "
                    "at runtime before the unary operator; keep as typed red "
                    "until a narrower callsite floor owns this shape. "
                    f"force_floor={observed}; blame={operation.blame}"
                )
            )
        return perform_operation(
            owner=operation.owner,
            blame=operation.blame,
            receiver=floor,
            operation=operation,
            ctx=ctx,
        )

    def force_floor(
        self,
        ctx: Any,
        *,
        owner: str,
        seen: frozenset[str] = frozenset(),
        depth: int = 0,
        budget: int = _FORCE_FLOOR_BUDGET,
        project_callsite: bool = True,
    ):
        key = repr(self.term)
        if depth >= budget or len(seen) >= budget:
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="callsite value demand budget exhausted",
                fix=(
                    f"callsite `{self.target_name}` exceeded force_floor dig budget "
                    f"{budget}; leave the bridge as axiomatic and record a DigRefusal"
                ),
            )
        if key in seen:
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="recursive callsite value demand",
                fix=(
                    f"callsite `{self.target_name}` recursively demanded its own "
                    "floor; leave the bridge as axiomatic and record a DigRefusal"
                ),
            )
        if (body := self.body) is None:
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="missing callsite body",
                fix=(
                    f"carry a factory-built body for callsite `{self.target_name}` "
                    "or leave the bridge as axiomatic"
                ),
            )
        if len(self.parameters) != len(self.arg_values):
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="callsite arity mismatch",
                fix=(
                    f"callsite `{self.target_name}` argument count does not match "
                    "its body; add argument binding sugar or leave the bridge axiomatic"
                ),
            )
        from sugar_lift_py_tests.outcome import Incomplete, complete_value

        reduce_ctx = _ctx_with_curried_args(ctx, self.parameters, self.arg_values)
        outcome = _reduce_callsite_body(body, reduce_ctx, blame=self.target_name)
        if isinstance(outcome, Incomplete):
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="Incomplete",
                fix=(
                    f"callsite `{self.target_name}` reduced to a runtime effect: "
                    f"{outcome.reason}; leave the floor absent and record a DigRefusal"
                ),
            )
        value = complete_value(outcome, owner=owner)
        floor = force_floor(
            value,
            reduce_ctx,
            owner=owner,
            seen=seen | {key},
            depth=depth + 1,
            budget=budget,
            project_callsite=project_callsite,
        )
        if project_callsite:
            _project_callsite_floor(
                floor,
                reduce_ctx,
                owner=owner,
                target_name=self.target_name,
                arg_values=self.arg_values,
            )
        return floor


def force_floor(
    value: FloorValue,
    ctx: Any,
    *,
    owner: str,
    seen: frozenset[str] = frozenset(),
    depth: int = 0,
    budget: int = _FORCE_FLOOR_BUDGET,
    project_callsite: bool = True,
) -> FloorValue:
    if isinstance(value, CallSiteValue):
        return value.force_floor(
            ctx,
            owner=owner,
            seen=seen,
            depth=depth,
            budget=budget,
            project_callsite=project_callsite,
        )
    return value


def _reduce_callsite_body(
    body: SugarBody | FunctionBodyUniverse,
    ctx: Any,
    *,
    blame: str,
):
    if isinstance(body, SugarBody):
        return body.reduce(ctx)
    if isinstance(body, FunctionBodyUniverse):
        from sugar_lift_py_tests.sugar.block_sugar import BlockSugar

        return BlockSugar(statements=body.statements, blame=blame).desugar(ctx)
    _force_floor_gap(
        owner="CallSiteValue.force_floor",
        target_name=blame,
        observed=type(body).__name__,
        fix="carry a SugarBody or FunctionBodyUniverse before demanding a callsite floor",
    )


def _project_callsite_floor(
    floor: FloorValue,
    ctx: Any,
    *,
    owner: str,
    target_name: str,
    arg_values: tuple[FloorValue, ...],
) -> None:
    from sugar_lift_py_tests.operations import (
        CallsiteProjectionOperation,
        perform_operation,
    )
    from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

    arg_terms = tuple(
        floor_to_term(arg, owner=f"{owner} callsite argument") for arg in arg_values
    )
    perform_operation(
        owner=owner,
        blame=target_name,
        receiver=floor,
        operation=CallsiteProjectionOperation(
            callee_name=target_name,
            arg_terms=arg_terms,
            owner=owner,
            blame=target_name,
        ),
        ctx=ctx,
    )


def _force_floor_gap(
    *,
    owner: str,
    target_name: str,
    observed: str,
    fix: str,
) -> NoReturn:
    from sugar_lift_py_tests.factory import (
        FactoryAuditRow,
        FactoryGap,
        FactoryGapInfo,
        GapKind,
        GapLocus,
    )

    info = FactoryGapInfo(
        owner=owner,
        blame=target_name,
        observed=observed,
        requested="force callsite floor",
        fix=fix,
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.PROJECTION,
    )
    raise FactoryGap(
        info,
        FactoryAuditRow(
            role="force_floor",
            status="floor-gap",
            observed=observed,
            blame=target_name,
            selected=None,
            candidates=[],
            message=info.message,
        ),
    )


def _ctx_with_curried_args(
    ctx: Any,
    parameters: tuple[str, ...],
    arg_values: tuple[FloorValue, ...],
):
    from sugar_lift_py_tests.temporal import curry_temporal

    return curry_temporal(
        ctx,
        parameters,
        arg_values,
        owner="CallSiteValue.force_floor",
        blame="<callsite>",
    )
