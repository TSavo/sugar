from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import NameErrorEffect
from sugar_lift_py_tests.floor.branch_result_coordinate import branch_result_guard
from sugar_lift_py_tests.ir import not_
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.binding_projection import (
    GuardedProjection,
    LoopGuardedProjection,
    UnboundProjection,
)
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar, Sugar


def _guarded_projection_faces(state: GuardedProjection):
    """The two faces owned by this authenticated branch-result projection,
    as the live loop item running now decides its slot (``branch_slot_here``):
    two items' reads of one ``if``'s binding never share one partition."""
    from sugar_lift_py_tests.outcome.exit_set import partition
    from sugar_lift_py_tests.sugar.evaluation_ref_sugar import branch_slot_here

    return partition(("binding.projection", branch_slot_here(state.slot).slot_id))


def _projection_guard(state: GuardedProjection, ctx, site):
    """``(guard, undecided)``: the guard a branch-result projection's true
    arm is read under, and whether the read owes the undecided member.  The
    guard is the test's own condition where the path reads the slot as it (a
    symbolic ``if``'s, ``branch_result_reading``), owing nothing; else the
    slot's guard, as the live loop item running now decides it
    (``branch_slot_here``), which no input decides, so the read owes the
    undecided member (``owing_undecided_slot``).  The one guard a read and
    a ``del`` of the projection select by (#7757)."""
    from sugar_lift_py_tests.floor.branch_result_coordinate import (
        branch_result_reading,
    )
    from sugar_lift_py_tests.sugar.evaluation_ref_sugar import branch_slot_here

    reading = branch_result_reading(state.slot, ctx)
    if reading is not None:
        return reading, False
    return branch_result_guard(branch_slot_here(state.slot), site), True


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


def decided_loop_exit(state: LoopGuardedProjection, ctx):
    """The completed face of ``state`` its loop left by on this path, where
    the loop's own run decided it, else ``None``.

    A loop whose items the reduction ran one by one decides its exit slot
    (``binding_state.loop_exit_slot``) on every exit it publishes on
    (``LoopRecurrenceSugar._exit_decision``): true when it left by
    exhaustion (``NormalExhaustion``), false when it left by its own
    ``break`` (``BreakExit``).  A read or a ``del`` after it takes that
    face, whole, as a read of a ground ``if``'s binding takes the arm its
    slot decided (``_decided_arm``): the other face is not taken here, and
    the guard the recurrence states the face by (``python.loop.exhausted``,
    the ``break``'s branch guard), which no input decides, is not stated on
    a path that ran.  A ``while`` run as its recurrence decides it too where
    its symbolic item decided the test (``LoopRecurrenceSugar._recurrence``).
    Undecided -- any other recurrence, a context the loop's publication did
    not reach -- the projection is read face by face under each face's
    guard, as before."""
    if state.target_cid is None:
        return None
    table = getattr(ctx, "ground_branch_results", None)
    if not isinstance(table, dict):
        return None
    from sugar_lift_py_tests.sugar.call_site_sugar import branch_result_read
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )
    from sugar_source_tree.binding_state import loop_exit_slot

    bound = branch_result_read(table, loop_exit_slot(state.target_cid).slot_id)
    if isinstance(bound, TrueBoolLiteralSugar):
        kind = "NormalExhaustion"
    elif isinstance(bound, FalseBoolLiteralSugar):
        kind = "BreakExit"
    else:
        return None
    faces = [face for face in state.completed_faces if face.completion_kind == kind]
    if len(faces) != 1:
        return None
    return faces[0]


def _read_loop_projection(
    state: LoopGuardedProjection, *, read_name: str, read_site, ctx, unbound=None
) -> ExitSet:
    left_by = decided_loop_exit(state, ctx)
    if left_by is not None:
        # The loop ran in hand on this path and left by this face: the read
        # is its binding, whole (``decided_loop_exit``).
        return _read_arm(
            left_by.state,
            read_name=read_name,
            read_site=read_site,
            ctx=ctx,
            unbound=unbound,
        )
    by_kind = _loop_exit_faces(state)
    exits = ExitSet(())
    for face in state.completed_faces:
        exits = exits.union(
            _read_arm(
                face.state,
                read_name=read_name,
                read_site=read_site,
                ctx=ctx,
                unbound=unbound,
            ).guarded(
                face.guard_formula,
                None if by_kind is None else by_kind[face.completion_kind],
            )
        )
    return exits.normalize()


def _read_arm(state, *, read_name: str, read_site, ctx, unbound=None) -> ExitSet:
    """One arm of a projection, joined with its peers under its own face.

    A join reads the arm's exits, so anything but exits there is refused
    by name.
    """
    from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

    return _require_exit_set(
        read_binding(
            state,
            read_name=read_name,
            read_site=read_site,
            ctx=ctx,
            unbound=unbound,
        ),
        owner="GuardedBindingReadSugar.read_binding",
    )


def _decided_arm(state: GuardedProjection, ctx):
    """The arm of ``state`` its slot selects where the reduction decided the
    slot (``ground_branch_results``, read as ``BranchResultRefSugar`` reads
    it), or ``None`` where it is undecided."""
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    table = getattr(ctx, "ground_branch_results", None)
    if not isinstance(table, dict):
        return None
    from sugar_lift_py_tests.sugar.call_site_sugar import branch_result_read
    from sugar_lift_py_tests.sugar.evaluation_ref_sugar import branch_slot_here

    bound = branch_result_read(table, branch_slot_here(state.slot, table).slot_id)
    if isinstance(bound, TrueBoolLiteralSugar):
        return state.when_true
    if isinstance(bound, FalseBoolLiteralSugar):
        return state.when_false
    return None


def read_binding(state, *, read_name: str, read_site, ctx, unbound=None) -> ExitSet:
    """The read of a binding projection: each arm the path may take, under
    its own guard and face, the arm a decided slot selects whole.

    ``unbound``: what an arm on which the name is unbound answers, for a
    reader that is not a read of the name (``PreLoopBindingReadSugar``: a
    loop's pre-loop value, which Python never reads); ``None`` for a read,
    where that arm is the ``NameError`` Python raises."""
    if isinstance(state, Sugar):
        # The whole read: the reaching value's own desugar.
        return state.desugar(ctx)
    if isinstance(state, UnboundProjection):
        if unbound is not None:
            return unbound(state)
        return ExitSet.halted(NameErrorEffect.at(name=read_name, site=read_site))
    if isinstance(state, LoopGuardedProjection):
        return _read_loop_projection(
            state,
            read_name=read_name,
            read_site=read_site,
            ctx=ctx,
            unbound=unbound,
        )
    if not isinstance(state, GuardedProjection):
        from sugar_lift_py_tests.sugar.delete_name_sugar import _unhandled_projection

        _unhandled_projection(state, verb="read", name=read_name, site=read_site)

    decided = _decided_arm(state, ctx)
    if decided is not None:
        # The reduction decided the slot on this path (a ground ``if``, a
        # live loop's write slot: ``BranchResultDecision``): the read is that
        # arm's, whole; the other arm is not taken here.
        return read_binding(
            decided,
            read_name=read_name,
            read_site=read_site,
            ctx=ctx,
            unbound=unbound,
        )
    guard, undecided = _projection_guard(state, ctx, read_site)
    true_face, false_face = _guarded_projection_faces(state)
    joined = (
        _read_arm(
            state.when_true,
            read_name=read_name,
            read_site=read_site,
            ctx=ctx,
            unbound=unbound,
        )
        .guarded(guard, true_face)
        .union(
            _read_arm(
                state.when_false,
                read_name=read_name,
                read_site=read_site,
                ctx=ctx,
                unbound=unbound,
            ).guarded(not_(guard), false_face)
        )
    )
    if not undecided:
        return joined
    from sugar_lift_py_tests.floor.branch_result_coordinate import (
        owing_undecided_slot,
    )

    return owing_undecided_slot(joined, read_site)


def _projection_term(state, *, owner: str):
    """Canonical testimony for one producer-authenticated binding projection."""
    from sugar_lift_py_tests.canonicalizer import blake3_512_of, encode_jcs
    from sugar_lift_py_tests.ir import ctor, formula_to_value, num, str_const

    if isinstance(state, ConstructedTermSugar):
        return state.to_term(owner=owner)
    if isinstance(state, UnboundProjection):
        cause = state.cause.seal()
        return ctor(
            "python:unbound-binding-projection",
            (
                str_const(state.name),
                str_const(cause.source_cid),
                num(cause.start),
                num(cause.end),
                str_const(cause.cid),
            ),
            symbol_kind="coordinate",
        )
    if isinstance(state, GuardedProjection):
        return ctor(
            "python:guarded-binding-projection",
            (
                str_const(state.slot.slot_id),
                _projection_term(state.when_true, owner=owner),
                _projection_term(state.when_false, owner=owner),
            ),
            symbol_kind="coordinate",
        )
    if isinstance(state, LoopGuardedProjection):
        if not isinstance(state.target_cid, str) or not state.target_cid.startswith(
            "blake3-512:"
        ):
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="_projection_term",
                blame=owner,
                observed="LoopGuardedProjection has no authenticated target CID (blake3-512:…)",
                requested="LoopGuardedProjection.target_cid as blake3-512 CID string",
                fix="carry authenticated loop target CID through projection construction",
            )
        faces = []
        for face in state.completed_faces:
            if face.guard_formula is None:
                from sugar_lift_py_tests.gap.panic import construction_panic_gap

                construction_panic_gap(
                    owner="_projection_term",
                    blame=owner,
                    observed="LoopGuardedProjection face has no exact guard formula",
                    requested="guard_formula testimony on each completed face",
                    fix="do not project CID-only guards; carry exact formula through the loop face",
                )
            if not isinstance(face.exit_partition_arity, int):
                from sugar_lift_py_tests.gap.panic import construction_panic_gap

                construction_panic_gap(
                    owner="_projection_term",
                    blame=owner,
                    observed="LoopGuardedProjection face has no integer exit_partition_arity",
                    requested="exit_partition_arity: int on each completed face",
                    fix="carry exit-family arity through loop projection construction",
                )
            guard_cid = blake3_512_of(
                encode_jcs(formula_to_value(face.guard_formula)).encode("utf-8")
            )
            faces.append(
                ctor(
                    "python:loop-guarded-binding-face",
                    (
                        str_const(face.completion_kind),
                        str_const(guard_cid),
                        num(face.exit_partition_arity),
                        _projection_term(face.state, owner=owner),
                    ),
                    symbol_kind="coordinate",
                )
            )
        return ctor(
            "python:loop-guarded-binding-projection",
            (str_const(state.target_cid), *faces),
            symbol_kind="coordinate",
        )
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner="_projection_term",
        blame=owner,
        observed=(
            f"binding projection species {type(state).__name__} has no "
            f"_projection_term arm"
        ),
        requested="Sugar | UnboundProjection | GuardedProjection | LoopGuardedProjection",
        fix=f"write _projection_term arm for {type(state).__name__}",
    )


@dataclass(frozen=True)
class GuardedBindingReadSugar(ConstructedTermSugar):
    name: str
    state: object
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> ExitSet:
        return read_binding(
            self.state, read_name=self.name, read_site=self.site, ctx=ctx
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:guarded-binding-read",
            (
                self.occurrence_term(owner=owner),
                str_const(self.name),
                _projection_term(self.state, owner=owner),
            ),
            symbol_kind="coordinate",
        )


@dataclass(frozen=True)
class PreLoopBindingReadSugar(GuardedBindingReadSugar):
    """The value a live loop's header starts with for a carried name whose
    pre-loop binding is a projection (bound on one arm of an ``if`` or an
    earlier loop, unbound on another: ``GuardedProjection``), read through
    the one read (``read_binding``) as a ``LoopProjectedBinding``'s product
    is (``LoopRecurrenceSugar._start``): each arm under its own guard, the
    arm a decided slot selects whole.

    The loop does not read the name: ``for x in xs:`` after ``if c: x = 1``
    raises nothing where ``c`` was false; the header starts unbound there.
    So an arm the read takes on which the name is unbound is never the
    ``NameError`` a read is: no start unbound on one arm and bound on
    another is stated here yet, so that arm is refused by name and the
    enclosing function is the proof's refused member, never the file
    crashed (``'GuardedProjection' object has no attribute 'desugar'``,
    #7757) and never a halt Python does not raise.  An arm the path does
    not take (a slot the reduction decided, a loop that ran in hand) is
    never read."""

    def desugar(self, ctx: object = None) -> ExitSet:
        return read_binding(
            self.state,
            read_name=self.name,
            read_site=self.site,
            ctx=ctx,
            unbound=self._starts_unbound,
        )

    def _starts_unbound(self, state: UnboundProjection) -> ExitSet:
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            owner="PreLoopBindingReadSugar",
            blame=self.site,
            observed=(
                f"`{self.name}` is unbound before the loop on a path the "
                f"loop is entered by (`{state.name}` unbound there): the "
                "loop's header starts unbound on that path and bound on "
                "another"
            ),
            requested=(
                "a loop header started unbound on the arm where its pre-loop "
                "binding is unbound, bound on the others"
            ),
            fix=(
                "start the header unbound on that arm "
                "(LoopRecurrenceSugar._start), never a NameError the loop "
                "does not raise"
            ),
        )
