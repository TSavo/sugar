from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import NameErrorEffect
from sugar_lift_py_tests.floor.branch_result_coordinate import branch_result_guard
from sugar_lift_py_tests.ir import not_
from sugar_lift_py_tests.outcome import ExitSet, Outcome, outcome_to_exitset
from sugar_lift_py_tests.outcome.exit_set import partition as _partition
from sugar_lift_py_tests.sugar.binding_projection import (
    GuardedProjection,
    LoopGuardedProjection,
    UnboundProjection,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar


def _loop_exit_faces(state: LoopGuardedProjection):
    """The producer's own exit-route family for this loop, or ``None``.

    A LOOP EXITS EXACTLY ONE WAY, AND THE LOOP SAYS SO. `live_loop_construction`
    mints a post-binding record for each exit route it owns -- `BreakExit` when
    the body can break, and always `NormalExhaustion` -- and declares how many
    it minted. `BodyFallthrough` is not among them and must never be: it is the
    latch input, the loop-back edge, not a way out. So this reads a family off
    authenticated testimony; it never re-derives one from how the guards happen
    to be spelled, from the completion kinds' names, or from the arms' types.

    Returns ``None`` (leaving every arm unstamped, gap loud) unless ALL of:

      - the producer declared an arity at all;
      - the declaration is the same on every face;
      - the faces present cover that declared arity exactly;
      - the completion kinds are distinct, so the sides can be told apart;
      - the occurrence is authenticated -- ``target_cid`` identifies WHICH loop.

    Any one of these failing means the testimony to admit a family was not
    earned here, and `ExitSetFactoringGap` staying loud is the correct output.
    """
    from sugar_lift_py_tests.outcome.exit_set import partition_family

    faces = state.completed_faces
    if state.target_cid is None or len(faces) < 2:
        return None
    arities = {face.exit_partition_arity for face in faces}
    if len(arities) != 1:
        return None
    arity = arities.pop()
    if arity is None or arity != len(faces):
        return None
    kinds = tuple(face.completion_kind for face in faces)
    if len(set(kinds)) != len(kinds) or "BodyFallthrough" in kinds:
        return None
    minted = partition_family(("loop.exit", state.target_cid), kinds)
    return dict(zip(kinds, minted, strict=True))


def _read_loop_projection(
    state: LoopGuardedProjection, *, read_name: str, read_site, ctx
) -> ExitSet:
    by_kind = _loop_exit_faces(state)
    exits = ExitSet(())
    for face in state.completed_faces:
        exits = exits.union(
            read_binding(
                face.state,
                read_name=read_name,
                read_site=read_site,
                ctx=ctx,
            ).guarded(
                face.guard_formula,
                None if by_kind is None else by_kind[face.completion_kind],
            )
        )
    return exits.normalize()


def read_binding(state, *, read_name: str, read_site, ctx) -> ExitSet:
    if isinstance(state, Sugar):
        return outcome_to_exitset(state.desugar(ctx))
    if isinstance(state, UnboundProjection):
        return ExitSet.halted(NameErrorEffect(name=read_name, site=read_site))
    if isinstance(state, LoopGuardedProjection):
        return _read_loop_projection(
            state, read_name=read_name, read_site=read_site, ctx=ctx
        )
    if not isinstance(state, GuardedProjection):
        from sugar_lift_py_tests.sugar.delete_name_sugar import _unhandled_projection

        _unhandled_projection(state, verb="read", name=read_name, site=read_site)

    guard = branch_result_guard(state.slot, read_site)
    # THE READ OWNS THIS SPLIT, AND NOW SAYS SO.
    #
    # A conditionally-bound name is one value under the branch result and
    # another under its negation. That is a two-way partition this producer
    # decides, and it used to guard both arms with no face at all -- so every
    # downstream `factor_completed` had nothing but guard SHAPE to go on, and
    # any rewrite or merge that moved the shape made a real partition
    # unprovable. Same shape as the loop before #6375: the producer already
    # named its routes (`when_true` / `when_false` over an authenticated slot)
    # and simply never minted the testimony.
    #
    # The owner is `state.slot`, the branch-result identity itself, NOT the
    # read site: two reads of the same conditional binding are governed by the
    # SAME branch outcome, so they must mint the same partition or arms that
    # genuinely exclude each other would look unrelated. `partition` addresses
    # by content, so this is reproducible rather than allocation-based.
    then_face, else_face = _partition(("binding.read", state.slot))
    return (
        read_binding(
            state.when_true,
            read_name=read_name,
            read_site=read_site,
            ctx=ctx,
        )
        .guarded(guard, then_face)
        .union(
            read_binding(
                state.when_false,
                read_name=read_name,
                read_site=read_site,
                ctx=ctx,
            ).guarded(not_(guard), else_face)
        )
    )


@dataclass(frozen=True)
class GuardedBindingReadSugar(Sugar):
    name: str
    state: object
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        return read_binding(
            self.state, read_name=self.name, read_site=self.site, ctx=ctx
        ).collapse()
