from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import BoundVar
from sugar_lift_py_tests.operations import (
    InplaceBinaryOperatorOperation,
    perform_operation,
)
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import aug_assign_return_witness
from sugar_lift_py_tests.sugar_body import SugarBody

_INPLACE_SYMBOL: dict[str, str] = {
    "Add": "+",
    "Sub": "-",
    "Mult": "*",
    "Div": "/",
    "FloorDiv": "//",
    "Mod": "%",
    "Pow": "**",
    "MatMult": "@",
    "BitAnd": "&",
    "BitOr": "|",
    "BitXor": "^",
    "LShift": "<<",
    "RShift": ">>",
}


@dataclass(frozen=True)
class AugAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """`x <op>= v` binds x to a lazy in-place binary operation over the old x."""

    name: str | None
    value: SugarBody | None
    runtime_reason: str | None = None
    blame: str = "<unknown>"

    @classmethod
    def owns(cls, fragment) -> bool:
        return fragment.observed == "AugAssign"

    @classmethod
    def witnesses(cls):
        return aug_assign_return_witness()

    @classmethod
    def build(cls, fragment, ctx):
        if (
            fragment.aug_assign_target().observed != "Name"
            or fragment.aug_assign_op() not in _INPLACE_SYMBOL
        ):
            return cls(
                name=None,
                value=None,
                runtime_reason=(
                    f"target {fragment.aug_assign_target().observed} with "
                    f"operator {fragment.aug_assign_op()}"
                ),
                blame=fragment.blame,
            )
        value = _AugAssignValue(
            operator=_INPLACE_SYMBOL[fragment.aug_assign_op()],
            left=ctx.build_body(fragment.aug_assign_target(), SugarRole.TERM),
            right=ctx.build_body(fragment.aug_assign_value(), SugarRole.TERM),
            blame=fragment.blame,
        )
        return cls(
            name=fragment.aug_assign_target().name_id(),
            value=SugarBody(value, SugarRole.TERM),
            blame=fragment.blame,
        )

    def desugar(self, ctx) -> Outcome:
        if self.runtime_reason is not None:
            return Incomplete(
                RuntimeEffect(
                    "augmented assignment runtime boundary: "
                    f"{self.runtime_reason} mutates runtime state; keep as typed "
                    "red until a narrower assignment floor owns this shape. "
                    f"blame={self.blame}"
                )
            )
        if self.name is None or self.value is None:
            raise TypeError("AugAssignSugar supported path must carry name and value")
        return Complete(BoundVar(self.name, self.value, scope=ctx))


@dataclass(frozen=True)
class _AugAssignValue:
    operator: str
    left: SugarBody
    right: SugarBody
    blame: str

    def __post_init__(self) -> None:
        if not isinstance(self.left, SugarBody):
            raise TypeError("AugAssignSugar left must be a factory-built body")
        if not isinstance(self.right, SugarBody):
            raise TypeError("AugAssignSugar right must be a factory-built body")

    def desugar(self, ctx) -> Outcome:
        left_outcome = self.left.reduce(ctx)
        if isinstance(left_outcome, Incomplete):
            return left_outcome
        right_outcome = self.right.reduce(ctx)
        if isinstance(right_outcome, Incomplete):
            return right_outcome
        left = complete_value(left_outcome, owner="AugAssignSugar left")
        right = complete_value(right_outcome, owner="AugAssignSugar right")
        return perform_operation(
            owner="AugAssignSugar",
            blame=self.blame,
            receiver=left,
            operation=InplaceBinaryOperatorOperation(
                operator=self.operator,
                right=right,
                owner="AugAssignSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )
