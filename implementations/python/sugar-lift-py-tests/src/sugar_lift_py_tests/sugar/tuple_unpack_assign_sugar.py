from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import BlockValue, BoundVar
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.tuple_unpack_projection import TupleUnpackProjection
from sugar_lift_py_tests.sugar.witness_examples import (
    typed_red_effect_witness,
    tuple_unpack_assign_return_witness,
)
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TupleUnpackAssignSugar(Sugar, role=SugarRole.STATEMENT):
    bindings: tuple[tuple[str, tuple[int, ...]], ...]
    receiver: SugarBody
    blame: str
    runtime_reason: str | None = None

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assign":
            return False
        targets = site.assign_targets()
        if len(targets) != 1 or targets[0].observed not in {"Tuple", "List"}:
            return False
        if site.assign_value().observed in {"Tuple", "List"}:
            return False
        if _contains_starred(targets[0]):
            return True
        return bool(_target_bindings(targets[0]))

    @classmethod
    def build(cls, site, ctx) -> "TupleUnpackAssignSugar":
        if not cls.owns(site):
            raise TypeError(
                "TupleUnpackAssignSugar claim built a non-unpack assignment"
            )
        target = site.assign_targets()[0]
        runtime_reason = None
        if _contains_starred(target):
            runtime_reason = (
                "starred rest target requires runtime sequence arity and slice "
                "materialization before binding"
            )
        return cls(
            bindings=() if runtime_reason is not None else _target_bindings(target),
            receiver=ctx.build_body(site.assign_value(), SugarRole.TERM),
            blame=site.blame,
            runtime_reason=runtime_reason,
        )

    @classmethod
    def witnesses(cls):
        return (
            tuple_unpack_assign_return_witness(),
            typed_red_effect_witness(
                name="starred_tuple_unpack_assign_runtime_effect",
                owner_sugar=cls.__name__,
                source=("def A(table):\n" "    header, *rest = table\n"),
                effect_class="RuntimeEffect",
                reason_needle="starred tuple-unpack assignment runtime boundary",
                blame_needle="test_witness.py:2:4",
                wrong_reason_needle="generator expression runtime boundary",
            ),
        )

    def _build(self, ctx) -> Outcome:
        if self.runtime_reason is not None:
            return Incomplete(
                RuntimeEffect(
                    "starred tuple-unpack assignment runtime boundary: "
                    "crime=starred assignment target requested as static binding; "
                    "owner=TupleUnpackAssignSugar; "
                    "shape=Assign target contains Starred; "
                    f"replacement=add a cited starred-unpack binding floor; "
                    f"{self.runtime_reason}; "
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
