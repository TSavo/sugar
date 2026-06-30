from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BlockValue, GuardedReturn, ReturnValue
from sugar_lift_py_tests.ir import eq, gt, lt, make_var, ne, not_, num, str_const
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


def _guard(stmt, extra: tuple):
    if isinstance(stmt, ReturnValue):
        return GuardedReturn(extra, stmt.value)
    if isinstance(stmt, GuardedReturn):
        return GuardedReturn(extra + stmt.guards, stmt.value)
    raise TypeError(f"if branch yielded a non-return outcome `{type(stmt).__name__}`")


@dataclass(frozen=True)
class IfSugar(Sugar, role=SugarRole.STATEMENT):
    """An `if` statement composes a test and TWO child blocks: the then-block and the
    else-block. Each branch's returns become GUARDED returns -- the then branch under
    the test, the else branch under its negation. Control flow is the composition of
    child blocks, not a walker; nesting is just blocks within blocks."""

    test: object  # a guard Formula lifted from the `if` test
    then: SugarBody
    else_block: object  # SugarBody | None

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
        return cls(test=_cf_guard(site.if_test()), then=then_block, else_block=else_block)

    def desugar(self, ctx) -> Outcome:
        then_bv = complete_value(self.then.reduce(ctx), owner="if then-block")
        guarded = [_guard(stmt, (self.test,)) for stmt in then_bv.statements]
        if self.else_block is not None:
            else_bv = complete_value(self.else_block.reduce(ctx), owner="if else-block")
            negated = (not_(self.test),)
            guarded.extend(_guard(stmt, negated) for stmt in else_bv.statements)
            return Complete(BlockValue(tuple(guarded)))
        return Complete(BlockValue(tuple(guarded), (not_(self.test),)))


def _cf_operand(frag):
    if frag.observed == "Name":
        return make_var(frag.name_id())
    if frag.observed == "PrimitiveLiteral" and not isinstance(frag.literal_value(), bool):
        val = frag.literal_value()
        if isinstance(val, int):
            return num(val)
        if isinstance(val, str):
            return str_const(val)
    raise TypeError(f"control-flow operand shape `{frag.observed}`")


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
        if op_name == "Gt":
            return gt(left, right)
        if op_name == "Lt":
            return lt(left, right)
    raise TypeError(f"control-flow guard shape `{frag.observed}`")
