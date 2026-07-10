# SPDX-License-Identifier: MIT OR Apache-2.0
"""Chained multi-target assignment (`a = b = expr`, `x, y = z = expr`).

Single-name `name = expr` is `AssignSugar`. Multi-target chains evaluate the
RHS once and assign left-to-right to each target (Python language reference).
Name targets alias the RHS source as BoundVar; fixed-arity Tuple/List of Names
project the same source via TupleUnpackProjection. Starred/attribute/subscript
targets stay typed RuntimeEffect until floors own those shapes.

Lift-probe (before): empty STATEMENT catalog for multi-target Assign →
FactoryGap `create sugar_lift_py_tests.sugar.assign.assign_sugar`.
Mechanism: missing AST recognizer for multi-target Assign (not a floor totalizer).
Residual locus: `system, node, … = infos = os.uname()` (platform/pandas dig).
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import BlockValue, BoundVar
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.tuple_unpack_projection import TupleUnpackProjection
from sugar_lift_py_tests.sugar.witness_examples import multi_target_assign_return_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class MultiTargetAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """Multi-target Assign chain → BoundVars (or typed red for unowned targets)."""

    bindings: tuple[tuple[str, tuple[int, ...]], ...]
    receiver: SugarBody
    blame: str
    runtime_reason: str | None = None

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assign":
            return False
        return len(site.assign_targets()) > 1

    @classmethod
    def witnesses(cls):
        return multi_target_assign_return_witness()

    @classmethod
    def build(cls, site, ctx) -> "MultiTargetAssignSugar":
        if not cls.owns(site):
            raise TypeError(
                "MultiTargetAssignSugar claim built a non-multi-target assignment"
            )
        bindings: list[tuple[str, tuple[int, ...]]] = []
        runtime_reason: str | None = None
        for target in site.assign_targets():
            if _contains_starred(target):
                runtime_reason = (
                    "starred rest target requires runtime sequence arity and slice "
                    "materialization before binding"
                )
                bindings = []
                break
            if target.observed == "Name":
                bindings.append((target.name_id(), ()))
                continue
            if target.observed in {"Tuple", "List"}:
                nested = _target_bindings(target)
                if not nested:
                    runtime_reason = (
                        f"unsupported multi-target element shape `{target.observed}` "
                        "with non-Name items"
                    )
                    bindings = []
                    break
                bindings.extend(nested)
                continue
            runtime_reason = (
                f"unsupported multi-target shape `{target.observed}` "
                "(need Name or fixed Tuple/List of Names)"
            )
            bindings = []
            break
        return cls(
            bindings=tuple(bindings),
            receiver=ctx.build_body(site.assign_value(), SugarRole.TERM),
            blame=site.blame,
            runtime_reason=runtime_reason,
        )

    def _build(self, ctx) -> Outcome:
        if self.runtime_reason is not None:
            return Incomplete(
                RuntimeEffect(
                    "multi-target assignment runtime boundary: "
                    "crime=chained assignment target not yet a static binding; "
                    "owner=MultiTargetAssignSugar; "
                    f"shape={self.runtime_reason}; "
                    "replacement=add a cited target binding floor; "
                    f"blame={self.blame}"
                )
            )
        return Complete(
            BlockValue(
                tuple(
                    BoundVar(
                        name,
                        _projection_body(self.receiver, path, blame=self.blame),
                        scope=ctx,
                    )
                    for name, path in self.bindings
                )
            )
        )


def _target_bindings(
    target,
    path: tuple[int, ...] = (),
) -> tuple[tuple[str, tuple[int, ...]], ...]:
    if target.observed == "Name":
        return ((target.name_id(), path),)
    if target.observed not in {"Tuple", "List"}:
        return ()
    bindings: list[tuple[str, tuple[int, ...]]] = []
    for index, item in enumerate(target.terms()):
        nested = _target_bindings(item, path + (index,))
        if not nested:
            return ()
        bindings.extend(nested)
    return tuple(bindings)


def _contains_starred(target) -> bool:
    if target.observed == "Starred":
        return True
    if target.observed not in {"Tuple", "List"}:
        return False
    return any(_contains_starred(item) for item in target.terms())


def _projection_body(
    receiver: SugarBody,
    path: tuple[int, ...],
    *,
    blame: str,
) -> SugarBody:
    body = receiver
    for index in path:
        body = SugarBody(
            TupleUnpackProjection(
                body,
                index,
                blame=blame,
            ),
            SugarRole.TERM,
        )
    return body
