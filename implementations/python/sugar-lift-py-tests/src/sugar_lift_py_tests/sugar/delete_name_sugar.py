from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import NameErrorEffect
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.floor.branch_result_coordinate import branch_result_guard
from sugar_lift_py_tests.ir import not_
from sugar_lift_py_tests.outcome import Complete, ExitSet, Outcome, outcome_to_exitset
from sugar_lift_py_tests.sugar.binding_projection import (
    GuardedProjection,
    LoopGuardedProjection,
    UnboundProjection,
)
from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import _loop_exit_faces
from sugar_lift_py_tests.sugar.sugar_base import Sugar


def _unhandled_projection(state, *, verb: str, name: str, site):
    """A binding projection constructor with no arm, NAMED.

    `BindingProjection` is a closed union of four constructors, and every verb
    over it (`read`, `delete`) must answer for all four. A bare
    `raise TypeError(type(state))` named neither the union nor the missing arm.
    """
    from sugar_lift_py_tests.gap.info import GapKind
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner=f"{verb}_binding",
        blame=site,
        observed=(
            f"binding projection {type(state).__name__} has no arm in the "
            f"`{verb}` verb over BindingProjection (name={name!r})"
        ),
        requested=(
            "every BindingProjection constructor answers every verb over it: "
            "Sugar, UnboundProjection, GuardedProjection, LoopGuardedProjection"
        ),
        fix=f"write the {type(state).__name__} arm of {verb}_binding",
        gap_kind=GapKind.SUGAR,
    )


def delete_binding(state, *, name: str, site, ctx) -> ExitSet:
    if isinstance(state, Sugar):
        return ExitSet.completed(BlockValue((), can_fall_through=True))
    if isinstance(state, UnboundProjection):
        return ExitSet.halted(NameErrorEffect(name=name, site=site))
    if isinstance(state, LoopGuardedProjection):
        # A name a loop bound on several completed faces is deleted ON EACH FACE,
        # under that face's guard. `read_binding` already reads the same union;
        # `del` is the other verb over the SAME projection, and it simply had no
        # arm for this constructor -- which is what
        # `TypeError: LoopGuardedProjection` was.
        partition_faces = _loop_exit_faces(state)
        exits = ExitSet(())
        for face in state.completed_faces:
            exits = exits.union(
                delete_binding(face.state, name=name, site=site, ctx=ctx).guarded(
                    face.guard_formula,
                    (
                        None
                        if partition_faces is None
                        else partition_faces[face.completion_kind]
                    ),
                )
            )
        return exits.normalize()
    if not isinstance(state, GuardedProjection):
        _unhandled_projection(state, verb="delete", name=name, site=site)
    guard = branch_result_guard(state.slot, site)
    return (
        delete_binding(state.when_true, name=name, site=site, ctx=ctx)
        .guarded(guard)
        .union(
            delete_binding(state.when_false, name=name, site=site, ctx=ctx).guarded(
                not_(guard)
            )
        )
    )


@dataclass(frozen=True)
class DeleteNameSugar(Sugar):
    name: str
    prior: object
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        return delete_binding(
            self.prior, name=self.name, site=self.site, ctx=ctx
        ).collapse()
