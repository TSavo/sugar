from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BlockValue, BoundVar
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.tuple_unpack_projection import TupleUnpackProjection
from sugar_lift_py_tests.sugar.witness_examples import (
    tuple_unpack_assign_return_witness,
)
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TupleUnpackAssignSugar(Sugar, role=SugarRole.STATEMENT):
    bindings: tuple[tuple[str, tuple[int, ...]], ...]
    receiver: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assign":
            return False
        targets = site.assign_targets()
        if len(targets) != 1 or targets[0].observed not in {"Tuple", "List"}:
            return False
        if site.assign_value().observed in {"Tuple", "List"}:
            return False
        return bool(_target_bindings(targets[0]))

    @classmethod
    def build(cls, site, ctx) -> "TupleUnpackAssignSugar":
        if not cls.owns(site):
            raise TypeError(
                "TupleUnpackAssignSugar claim built a non-unpack assignment"
            )
        return cls(
            bindings=_target_bindings(site.assign_targets()[0]),
            receiver=ctx.build_body(site.assign_value(), SugarRole.TERM),
            blame=site.blame,
        )

    @classmethod
    def witnesses(cls):
        return tuple_unpack_assign_return_witness()

    def _build(self, ctx) -> Outcome:
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
