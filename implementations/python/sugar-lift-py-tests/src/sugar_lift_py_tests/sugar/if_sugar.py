from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import (
    BlockValue,
)
from sugar_lift_py_tests.ir import (
    ctor,
    eq,
    gt,
    gte,
    identity,
    lt,
    lte,
    make_var,
    ne,
    not_,
    num,
    real_lit,
    str_const,
)
from sugar_lift_py_tests.operations import ControlFlowGuardOperation, perform_operation
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class IfSugar(Sugar, role=SugarRole.STATEMENT):
    """An `if` statement composes a test and TWO child blocks: the then-block and the
    else-block. Each branch's returns become GUARDED returns -- the then branch under
    the test, the else branch under its negation. Control flow is the composition of
    child blocks, not a walker; nesting is just blocks within blocks."""

    test: object  # a guard Formula lifted from the `if` test
    then: SugarBody
    else_block: object  # SugarBody | None
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "If"

    @classmethod
    def build(cls, site, ctx) -> "IfSugar":
        if site.observed != "If":
            raise TypeError("IfSugar claim built a non-if")
        body_sites = site.statements()
        then_block = ctx.build_body(body_sites[0], SugarRole.STATEMENT)
        else_block = (
            ctx.build_body(body_sites[1], SugarRole.STATEMENT)
            if len(body_sites) > 1
            else None
        )
        return cls(
            test=_cf_guard(site.if_test()),
            then=then_block,
            else_block=else_block,
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        then_bv = complete_value(self.then.reduce(ctx), owner="if then-block")
        then_guarded = self._guard_block(then_bv, (self.test,), ctx)
        guarded = list(then_guarded.statements)
        if self.else_block is not None:
            else_bv = complete_value(self.else_block.reduce(ctx), owner="if else-block")
            negated = (not_(self.test),)
            else_guarded = self._guard_block(else_bv, negated, ctx)
            guarded.extend(else_guarded.statements)
            return Complete(BlockValue(tuple(guarded)))
        return Complete(BlockValue(tuple(guarded), (not_(self.test),)))

    def _guard_block(self, block: BlockValue, guards: tuple, ctx) -> BlockValue:
        return complete_value(
            perform_operation(
                owner="IfSugar",
                blame=self.blame,
                receiver=block,
                method_name="guard_with",
                operation=ControlFlowGuardOperation(
                    guards,
                    owner="IfSugar",
                    blame=self.blame,
                ),
                ctx=ctx,
            ),
            owner="if guarded block",
        )


def _cf_operand(frag):
    if frag.observed == "Name":
        return make_var(frag.name_id())
    if frag.observed == "PrimitiveLiteral" and not isinstance(
        frag.literal_value(), bool
    ):
        val = frag.literal_value()
        if isinstance(val, int):
            return num(val)
        if isinstance(val, float):
            return real_lit(format(Decimal(str(val)), "f"))
        if isinstance(val, str):
            return str_const(val)
        if val is None:
            return ctor("None", [])
    if frag.observed == "Tuple":
        return ctor("tuple", [_cf_operand(term) for term in frag.terms()])
    raise TypeError(_cf_gap_message("operand", frag, observed=frag.observed))


def _cf_guard(frag):
    if (
        frag.observed == "Compare"
        and len(frag.compare_ops()) == 1
        and len(frag.compare_comparators()) == 1
    ):
        left = _cf_operand(frag.compare_left())
        right = _cf_operand(frag.compare_comparators()[0])
        op_name = frag.compare_ops()[0]
        if op_name == "Eq":
            return eq(left, right)
        if op_name == "NotEq":
            return ne(left, right)
        if op_name == "Is":
            return identity(left, right)
        if op_name == "IsNot":
            return not_(identity(left, right))
        if op_name == "Gt":
            return gt(left, right)
        if op_name == "GtE":
            return gte(left, right)
        if op_name == "Lt":
            return lt(left, right)
        if op_name == "LtE":
            return lte(left, right)
    observed = frag.observed
    if frag.observed == "Compare":
        observed = f"Compare:{','.join(frag.compare_ops()) or 'unknown'}"
    if frag.observed == "Call":
        target = (
            frag.call_qualified_target_name() or frag.call_target_name() or "unknown"
        )
        observed = f"call-control-flow-guard:{target}"
    raise TypeError(_cf_gap_message("guard", frag, observed=observed))


def _cf_gap_message(kind: str, frag, *, observed: str) -> str:
    fix = f"add IfSugar lowering for {observed}"
    if kind == "guard" and observed.startswith("call-control-flow-guard:"):
        target = observed.split(":", 1)[1]
        fix = f"add IfSugar lowering for guard call `{target}` or emit a real effect"
    return (
        f"write more Sugar for control-flow {kind}: owner=IfSugar "
        f"blame={frag.blame} observed={observed} requested=control-flow {kind} "
        f"fix={fix}"
    )
