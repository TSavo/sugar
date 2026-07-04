from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.ir import Term, ctor

from .floor_value import FloorValue
from .term_value import TermValue


@dataclass(frozen=True)
class SetLiteralValue(FloorValue):
    """A structural Python set literal term with deterministic support order."""

    non_fol_support = True

    items: tuple[Term, ...]

    def to_term(self, *, owner: str) -> Term:
        del owner
        return ctor("python:set", list(self.items))

    def call_method_with(self, operation: Any, ctx: object) -> Any:
        del ctx
        if operation.name == "__len__" and not operation.arguments:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(len(self.items)))
        _call_method_gap(
            owner=operation.owner,
            blame=operation.blame,
            observed=f"SetLiteralValue.{operation.name}",
            requested="set builtin method floor",
            fix=f"add SetLiteralValue method floor for `{operation.name}`",
        )


def _call_method_gap(
    *,
    owner: str,
    blame: str,
    observed: str,
    requested: str,
    fix: str,
):
    from sugar_lift_py_tests.factory import (
        FactoryAuditRow,
        FactoryGap,
        FactoryGapInfo,
        GapKind,
        GapLocus,
    )

    info = FactoryGapInfo(
        owner=owner,
        blame=blame,
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.CONSTRUCTION,
    )
    raise FactoryGap(
        info,
        FactoryAuditRow(
            role=requested,
            status="floor-gap",
            observed=observed,
            blame=blame,
            selected=None,
            candidates=[],
            message=info.message,
        ),
    )
