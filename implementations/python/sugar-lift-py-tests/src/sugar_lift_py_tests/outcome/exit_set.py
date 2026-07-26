"""Guarded block exits: the effect-dimension phi for statement sequencing."""

from __future__ import annotations

from dataclasses import dataclass, field as _dataclass_field
from typing import Callable, Generic, TypeVar

from sugar_lift_py_tests.effect import Effect, require_effect
from sugar_lift_py_tests.ir import Formula, and_, not_, or_

from .complete import Complete
from .incomplete import Incomplete

T = TypeVar("T")
U = TypeVar("U")


def true_guard() -> Formula:
    """The existing FOL encoding of truth: an empty conjunction."""
    return and_([])


def false_guard() -> Formula:
    return not_(true_guard())


def _is_true(guard: Formula) -> bool:
    return guard == true_guard()


def _is_false(guard: Formula) -> bool:
    return guard == false_guard()


def _is_negation(left: Formula, right: Formula) -> bool:
    return (
        getattr(left, "kind", None) == "not"
        and getattr(left, "operands", ()) == (right,)
    ) or (
        getattr(right, "kind", None) == "not"
        and getattr(right, "operands", ()) == (left,)
    )


def complement_guard(guard: Formula) -> Formula:
    """The other face of a partition, without stacking a second ``not``.

    ``complement_guard(not_(g)) is g``-shaped, so a guarded pair built from
    either direction spells the same two formulas. Double negation would still
    normalize (``_is_negation`` looks one level deep), but it would leak an
    ``not not g`` into the emitted FOL, and the FOL is the deliverable.
    """
    if getattr(guard, "kind", None) == "not":
        operands = getattr(guard, "operands", ())
        if len(operands) == 1:
            return operands[0]
    return not_(guard)


class ExitSetFactoringGap(ValueError):
    """A completed face that a guarded-value chain cannot faithfully carry.

    Loud on contact, in the same shape as ``SourceCallBindingGap``: the message
    names the two guards, why the collapse would lose an outcome, and the fix.

    Carries the two refusing ARMS as well as the prose (#6356). A census that
    has to re-derive them from the message is parsing a repr, and the split
    between "a producer failed to testify" and "no exclusion is available"
    is read off carried testimony -- see `outcome/factoring_gap_kind.py`.
    This is data on the exception, not a change to when it is raised.
    """

    def __init__(self, message: str, left=None, right=None) -> None:
        super().__init__(message)
        self.left = left
        self.right = right

    def classification(self):
        """The (a)/(b) split for this occurrence, or None if arms are absent."""
        if self.left is None or self.right is None:
            return None
        from sugar_lift_py_tests.outcome.factoring_gap_kind import (
            classify_factoring_gap,
        )

        return classify_factoring_gap(self.left, self.right)


@dataclass(frozen=True)
class PartitionFace:
    """Testimony that this exit lies on ONE named side of a producer's split.

    The producer that decided to branch mints both faces at that moment (see
    ``partition``) and applies one to each arm. Two exits carrying the same
    ``partition`` with different ``side`` provably cannot both hold, because
    the producer SAID SO when it split — nobody re-derives it from how the
    guards happen to be spelled.

    This is the difference the factoring gap turns on. ``_are_exclusive`` is a
    sound but shallow prover over guard SHAPE: it sees ``g`` against ``not g``
    one literal deep and nothing else. A partition that survives a disjunctive
    merge, a nested conjunction, or a value-level rewrite is still a partition,
    but its shape no longer advertises it. Carried testimony does not decay
    that way.
    """

    partition: object
    side: object
    arity: int | None = None
    """How many faces the producer declared for this origin, when it said.

    A pair minted by ``partition`` declares 2. A family minted by
    ``partition_family`` declares its own size. ``None`` is a face from a
    producer that never stated a family size, and such a face can carry
    pairwise exclusion but never COMPLETENESS -- see ``_complete_family``.
    """


def partition_family(
    owner: object, sides: tuple
) -> tuple[PartitionFace, ...]:
    """Mint an EXHAUSTIVE family of faces over ONE authenticated origin (#6356).

    ``partition`` covers a two-way split. A producer that decides among n
    routes -- a loop completing by break or by exhaustion, a dispatch over a
    closed set of outcomes -- owns an n-way split, and until now had no way to
    say so. `_faces_exclusive` already handles n unchanged (it only asks
    whether two arms carry the same origin with a different side), so the
    prover needed nothing; the MINT and the carried arity are what was missing.

    ``sides`` names every member, and the tuple's length is recorded on every
    face as its ``arity``. That is what makes COMPLETENESS checkable later:
    a set of arms covering fewer than ``arity`` distinct sides is a partial
    partition, and a partial partition is not a partition.

    THE PRODUCER MUST OWN THE WHOLE SPLIT. Minting a family over routes the
    producer does not decide, or omitting a route it does, asserts an
    exhaustiveness that is not true -- and unlike a pairwise face, an untrue
    family licenses collapsing a face that was never accounted for. The
    refusal in ``factor_completed`` exists for exactly the case where no such
    testimony was earned; do not mint one to reach it.
    """
    if len(sides) < 2:
        raise ValueError(
            "a partition family needs at least two faces: "
            f"owner=partition_family observed={len(sides)} sides "
            "replacement=a one-way split is not a split; do not mint testimony "
            "for it"
        )
    if len(set(sides)) != len(sides):
        raise ValueError(
            "a partition family needs DISTINCT faces: "
            f"owner=partition_family observed={sides!r} "
            "replacement=two members that cannot be told apart cannot carry "
            "an exclusion between them"
        )
    token = ("sugar.exit_set.partition", owner)
    return tuple(PartitionFace(token, side, len(sides)) for side in sides)


def _complete_family(arms) -> bool:
    """Whether these arms ARE one producer's complete, exhaustive partition.

    ALL of the following, and same-type is deliberately NOT among them:

      - every arm carries a face of ONE shared authenticated origin;
      - that origin declared an arity (an unstated family cannot be complete);
      - the arms' sides over it are pairwise DISTINCT;
      - they cover the declared arity exactly -- every face retained, none
        invented.

    Same destination type is a hint and never an admission: two
    ``PredicateValue`` arms from unrelated producers agree in type and share
    no origin at all. Type agreement is exactly the trap the two measured
    remaining-work rows are shaped like.
    """
    if len(arms) < 2:
        return False
    origins = None
    for arm in arms:
        faces = {face.partition for face in arm.faces if face.arity is not None}
        origins = faces if origins is None else (origins & faces)
        if not origins:
            return False
    for origin in origins:
        sides, arity = [], None
        for arm in arms:
            members = [f for f in arm.faces if f.partition == origin]
            # A MERGED arm can carry several sides of one origin (see
            # `_merge_faces`). It is one arm standing for several members, so
            # it cannot be counted as the single member the arity test needs;
            # admitting it would let two arms "cover" a three-way family. The
            # pairwise rule below still separates it on disjoint side sets --
            # this door just declines to call the family complete.
            if len(members) != 1:
                break
            sides.append(members[0].side)
            arity = members[0].arity
        else:
            if arity == len(arms) == len(set(sides)):
                return True
    return False


def partition(owner: object) -> tuple[PartitionFace, PartitionFace]:
    """Mint the two faces of a split OWNED by ``owner``.

    ``owner`` is the producing sugar's own identity for this one branch
    decision — a site key, a fragment coordinate, anything it can content
    address. It is testimony, not a hint: the faces are complementary because
    this call created them as a pair, not because a formula looks negated.

    A producer that does not own a genuine two-way split must not call this.
    Handing unrelated arms faces of one partition would assert an exclusion
    that does not hold, and the refusal in ``factor_completed`` exists to catch
    exactly the case where no such testimony was ever earned.
    """
    token = ("sugar.exit_set.partition", owner)
    return PartitionFace(token, True, 2), PartitionFace(token, False, 2)


_NO_FACES: frozenset[PartitionFace] = frozenset()


def _sides_by_partition(
    faces: frozenset[PartitionFace],
) -> dict[object, set[object]]:
    """Every side an arm is known to lie on, grouped by the split that named it.

    An arm usually carries ONE side per partition. A MERGED arm carries several:
    ``normalize`` disjoins two equal destinations, and the merged arm holds
    wherever either contributor did, so it lies on one side of ``{range,
    single}`` without saying which. That is a truthful, weaker statement, and
    the set is how it is spelled.
    """
    sides: dict[object, set[object]] = {}
    for face in faces:
        sides.setdefault(face.partition, set()).add(face.side)
    return sides


def _merge_faces(
    left: frozenset[PartitionFace], right: frozenset[PartitionFace]
) -> frozenset[PartitionFace]:
    """Testimony that survives a disjoining merge of two equal destinations.

    THE RULE IS PER PARTITION, and it was previously a plain set intersection.
    That answered the question "which identical faces did both carry", which is
    the right answer only when the arms lie on the same side. Two arms on
    DIFFERENT sides of one split still jointly testify something true and
    useful about the merged arm -- it is on one of those two sides, and on no
    other -- and the intersection threw that away, leaving the merged arm
    unstamped and its refusal unclosable by any producer.

    So: a split only ONE contributor named is dropped (the other claims nothing
    there, and an unclaimed side is not an exclusion). A split BOTH named keeps
    every side either of them could be on. That is weaker than each contributor
    alone, which is correct -- a merged arm knows less -- and it is not nothing.

    This does not let exclusivity be forged. ``_faces_exclusive`` asks for
    DISJOINT side sets, so a merged arm covering `{range, single}` is provably
    apart only from arms covering neither, which is exactly what the producer's
    own mint already asserted.
    """
    left_sides = _sides_by_partition(left)
    right_sides = _sides_by_partition(right)
    shared = left_sides.keys() & right_sides.keys()
    return frozenset(
        face for face in (left | right) if face.partition in shared
    )


def _faces_exclusive(
    left: frozenset[PartitionFace], right: frozenset[PartitionFace]
) -> bool:
    """Whether carried testimony alone proves the two arms cannot both hold.

    DISJOINT SIDE SETS over a SHARED partition. The producer said its sides are
    mutually exclusive when it minted them, so if everything the left arm could
    be is something the right arm cannot be, they cannot both hold. With one
    side each -- every face a producer mints directly -- this is exactly the
    ``!=`` it replaces; the sets only ever grow through a merge.

    Sound in the same direction as before: a False answer is "not proven",
    never "proven to overlap".
    """
    if not left or not right:
        return False
    right_sides = _sides_by_partition(right)
    for partition_id, sides in _sides_by_partition(left).items():
        other = right_sides.get(partition_id)
        if other is not None and not (sides & other):
            return True
    return False


def _conjuncts(guard: Formula) -> tuple[Formula, ...]:
    """Flatten a conjunction into its literals; anything else is one literal."""
    if getattr(guard, "kind", None) == "and":
        flattened: list[Formula] = []
        for operand in getattr(guard, "operands", ()):
            flattened.extend(_conjuncts(operand))
        return tuple(flattened)
    return (guard,)


def _partition_exclusive(
    left: frozenset[tuple[str, int]] | None,
    right: frozenset[tuple[str, int]] | None,
) -> bool:
    """Whether two arms carry opposite faces of one authenticated partition."""
    if not left or not right:
        return False
    for partition_id, face in left:
        for other_id, other_face in right:
            if partition_id == other_id and face != other_face:
                return True
    return False


def _union_partition(
    left: frozenset[tuple[str, int]] | None,
    right: frozenset[tuple[str, int]] | None,
) -> frozenset[tuple[str, int]] | None:
    """Accumulate partition faces through sequencing."""
    if left is None and right is None:
        return None
    return frozenset((*(left or ()), *(right or ())))


def _are_exclusive(left: Formula, right: Formula) -> bool:
    """Whether two guards provably cannot hold together, syntactically.

    Branch joins produce guards that carry a literal and its negation (``g``
    against ``not g``), which is why one level of literal comparison is enough
    for the shapes the tower builds. This is a SOUND-ONLY test: a False answer
    means "not provably exclusive", never "provably overlapping". Factoring
    refuses on a False answer rather than assuming a partition.
    """
    if _is_false(left) or _is_false(right):
        return True
    right_literals = frozenset(_conjuncts(right))
    for literal in _conjuncts(left):
        if complement_guard(literal) in right_literals:
            return True
    return False


def _and_guards(left: Formula, right: Formula) -> Formula:
    if _is_false(left) or _is_false(right) or _is_negation(left, right):
        return false_guard()
    if _is_true(left):
        return right
    if _is_true(right) or left == right:
        return left
    return and_([left, right])


def _or_guards(left: Formula, right: Formula) -> Formula:
    if _is_true(left) or _is_true(right) or _is_negation(left, right):
        return true_guard()
    if _is_false(left):
        return right
    if _is_false(right) or left == right:
        return left
    if getattr(left, "kind", None) == "and" and getattr(right, "kind", None) == "not":
        return or_([right, left])
    return or_([left, right])


# Sentinel for a destination that cannot be hashed. Not an error and not a
# reason to drop an arm: such an arm takes the original full scan.
_UNHASHABLE = object()

# Every unhashable destination that took the scan path, by exit kind. This is
# the measured-fallback receipt: if this list is ever non-empty in a real run,
# the slow path is real and someone must see it, rather than the quadratic
# quietly surviving inside a "fixed" normalizer.
_UNHASHABLE_DESTINATIONS: list[str] = []


def _unhashable_destination_count() -> int:
    """How many arms took the full-scan path (test / diagnostics only)."""
    return len(_UNHASHABLE_DESTINATIONS)


def _obligations(exit_: "Exit[T]") -> tuple:
    """An arm's obligations by content address, order-free (#6352).

    Keyed by ``demand_cid`` -- the obligation's own content address -- never by
    hashing the carrier, which holds a floor value and a term. Both arm kinds
    answer here: a completed face owes exactly the way a halted face does.
    """
    return tuple(
        sorted(
            demand.demand_cid
            for entry in exit_.pending_contracts
            for demand in entry.demands
        )
    )


def _destination_key(exit_: "Exit[T]") -> object:
    """Bucket key for an exit's DESTINATION, ignoring its guard.

    Two exits merge exactly when their destinations are equal, so the guard —
    the thing the merge rewrites — must not enter the key. Returns
    ``_UNHASHABLE`` when the destination cannot be hashed.
    """
    try:
        if isinstance(exit_, Completed):
            # Obligations are part of the destination on this face too: two
            # completed arms owing different things are different destinations.
            return ("completed", hash(exit_.value), _obligations(exit_))
        return (
            "halted",
            hash(exit_.effect),
            hash(exit_.state),
            _obligations(exit_),
        )
    except TypeError:
        return _UNHASHABLE


@dataclass(frozen=True)
class Completed(Generic[T]):
    """Control left with this value, under this guard.

    ``pending_contracts`` is the COMPLETED face of the parameter-contract
    carrier, the twin of the field ``Halted`` has carried since #6352. An
    operation distributed onto a value that already owed a caller obligation
    can answer with a partition -- `(a if c else b)[i]` where the subscript
    enrolled `python:indexable(b)` and the following step contained a store --
    and until this field existed the exit algebra had no arm that held a value
    together with an undischarged obligation. That was the ONE remaining LOUD
    category in ``single_outcome_law.rewrap_pending``, and the panic said so:
    "give the exit algebra an arm for a pending contract demand, so each
    completed face carries the demands weakened under its own guard".

    ENTRIES ARE CARRIED AS INCURRED, NOT PRE-WEAKENED. The arm's own ``guard``
    already states the face it is owed on, so `g -> D` is minted exactly once,
    at the block boundary that enrols it
    (``function_universe_sugar._enrol_exit_obligations``), under the guard the
    arm finally holds. Weakening at every restriction instead re-mints a
    ``demand_cid`` -- a blake3 over the JCS of the formula -- on every
    ``guarded``, ``sequence`` and ``and_exit`` step, and since a re-minted
    obligation is a DIFFERENT destination, it also stops arms merging in
    ``normalize``. Measured on pandas `core/reshape/merge.py`: minting per
    restriction did not finish the file in 13 minutes at 600MB resident, with
    the sample dominated by blake3 and JCS encoding; minting once does. Same
    obligation, same face, one mint.

    Like ``Halted.pending_contracts`` it is part of the DESTINATION, not
    testimony: two arms owing different things are different destinations and
    must not merge under a disjunction. Obligations are therefore compared,
    unlike ``faces``.
    """

    guard: Formula
    value: T
    # Testimony ABOUT this arm, never part of what it denotes: two arms with the
    # same guard and destination are the same exit whether or not a producer
    # stamped them. Excluded from compare/repr so carrying testimony cannot
    # perturb exit equality, normalize's merge, collapse, or any golden repr.
    faces: frozenset[PartitionFace] = _dataclass_field(
        default=_NO_FACES, compare=False, repr=False
    )
    pending_contracts: tuple = ()


@dataclass(frozen=True)
class Halted:
    """Control left with this effect, under this guard, from this state.

    ``pending_contracts`` conserves obligations incurred BEFORE the effect
    across the ``Incomplete`` -> halted conversion (#6352). Each is already
    weakened under this arm's own guard by ``outcome_to_exitset``, so the arm
    carries ``g -> D`` rather than a bare ``D``.

    It is deliberately NOT routed like ``faces``. A merged arm holds under a
    DISJUNCTION, so partition testimony may only keep what every contributing
    arm carried -- intersecting is what stops a merged arm claiming a face it
    held on one side only. Obligations must not be intersected (that drops one)
    and must not be unioned (that owes one on a face that never runs), so they
    take neither route: they are part of the DESTINATION, and two arms owing
    different things are different destinations that never merge at all.
    """

    guard: Formula
    effect: Effect
    state: object | None = None
    faces: frozenset[PartitionFace] = _dataclass_field(
        default=_NO_FACES, compare=False, repr=False
    )
    pending_contracts: tuple = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect", require_effect(self.effect))


Exit = Completed[T] | Halted


@dataclass(frozen=True)
class ExitSet(Generic[T]):
    """A partition of reachable execution into completed and halted exits."""

    exits: tuple[Exit[T], ...]

    @classmethod
    def completed(cls, value: T, guard: Formula | None = None) -> "ExitSet[T]":
        return cls((Completed(guard or true_guard(), value),)).normalize()

    @classmethod
    def halted(
        cls, effect: Effect, guard: Formula | None = None, state=None
    ) -> "ExitSet[T]":
        return cls((Halted(guard or true_guard(), effect, state),)).normalize()

    @classmethod
    def conditional_halt(cls, guard: Formula, effect: Effect, state: T) -> "ExitSet[T]":
        # A halt-or-not split this constructor owns outright: mint it rather
        # than leave the exclusion legible only in the ``not_`` spelling.
        halt_face, pass_face = partition(("conditional_halt", guard))
        return cls(
            (
                Halted(guard, effect, state, frozenset({halt_face})),
                Completed(not_(guard), state, frozenset({pass_face})),
            )
        ).normalize()

    def union(self, other: "ExitSet[T]") -> "ExitSet[T]":
        return ExitSet((*self.exits, *other.exits)).normalize()

    def guarded(self, guard: Formula, face: PartitionFace | None = None) -> "ExitSet[T]":
        """Restrict every exit to one branch of an enclosing partition.

        ``face`` is the caller's testimony that ``guard`` is one named side of a
        split it owns (see ``partition``). It rides along on every restricted
        exit so that a later ``factor_completed`` can read the exclusion off the
        arms instead of trying to re-prove it from guard shape. Omitting it is
        the honest default for a restriction that is not a partition face.

        Obligations RIDE ALONG unchanged and narrow with the arm's guard, which
        is the whole point of carrying them on the arm: ``combined`` is the face
        they are owed on, and `combined -> D` is minted once at enrolment. This
        method used to rebuild each arm from its guard, effect and state alone,
        so ``Halted.pending_contracts`` was dropped here outright -- conserved
        across the `Incomplete` -> halted conversion by #6352, then lost one
        call later.
        """
        exits: list[Exit[T]] = []
        for exit_ in self.exits:
            combined = _and_guards(guard, exit_.guard)
            faces = exit_.faces if face is None else exit_.faces | {face}
            owed = exit_.pending_contracts
            if isinstance(exit_, Completed):
                exits.append(Completed(combined, exit_.value, faces, owed))
            else:
                exits.append(
                    Halted(combined, exit_.effect, exit_.state, faces, owed)
                )
        return ExitSet(tuple(exits)).normalize()

    def with_partition_face(self, partition_id: str, face: int) -> "ExitSet[T]":
        """Stamp every completed arm with one authenticated partition face.

        Face is 0/1 for then/else of one producer-owned branch. Nested joins
        accumulate faces; two arms are exclusive when they disagree on any
        shared partition_id.
        """
        face_key = (partition_id, face)
        exits: list[Exit[T]] = []
        for exit_ in self.exits:
            if isinstance(exit_, Completed):
                stamped = frozenset((*((exit_.partition or frozenset())), face_key))
                exits.append(Completed(exit_.guard, exit_.value, stamped))
            else:
                exits.append(exit_)
        return ExitSet(tuple(exits))

    def factor_completed(self) -> "ExitSet[T]":
        """Collapse the completed FACE into one arm carrying a guarded value.

        This is the factoring primitive #6309 is built on. An ExitSet with
        several completed arms is a partition of the completed face over guards;
        the SAME partition can live at the exit level (m arms, one value each)
        or at the value level (one arm, a ``GuardedValue`` chain). Both retain
        every arm's guard and every arm's value — nothing is pruned, nothing is
        assumed to succeed, nothing is capped.

        The difference is what happens when such a face is SEQUENCED. Exit-level
        arms multiply: k steps of m arms distribute into m ** k arms, because
        ``sequence`` appends every exit of the tail under every completed exit of
        the prefix. Value-level arms compose: k steps contribute k guarded values
        to one arm, so both work and storage grow linearly in k. Same denotation,
        different growth — which is the whole fix.

        Halted arms are untouched: the halted face is not part of the value, so
        it stays at the exit level where it already grows linearly.

        REFUSES loudly when the completed arms are not provably pairwise
        exclusive. A ``GuardedValue`` chain is first-match-wins, so it denotes
        the same face as the arms only when at most one arm's guard can hold.
        Two overlapping completed arms with different values mean both values are
        reachable together — a set, not a selection — and quietly picking the
        first would be a silent semantic change. There is no materializing
        fallback here on purpose: the exponential is the defect, so the honest
        answer is a named gap, not a return to it.
        """
        completed = [e for e in self.exits if isinstance(e, Completed)]
        if len(completed) <= 1:
            return self

        # THE FAMILY ADMISSION (#6356). A producer that owns an n-way split and
        # says so -- one authenticated origin, distinct sides, the declared
        # arity covered exactly -- has proved pairwise exclusivity for the whole
        # set in one statement, and the pairwise scan below would have to
        # re-derive it from guard shape it may no longer be spelled in.
        #
        # Admission needs the WHOLE family. An incomplete one is not a
        # partition: a missing face is an outcome nobody accounted for, and
        # collapsing the rest would drop it. Same destination TYPE is not part
        # of the test and must never become part of it -- two arms of one type
        # from unrelated producers share no origin, which is exactly the shape
        # the measured remaining-work rows have.
        if _complete_family(completed):
            return self._factored(completed)

        for index, arm in enumerate(completed):
            for other in completed[index + 1 :]:
                # Carried testimony first: a producer that minted these as two
                # faces of ONE split already answered this, and its answer does
                # not decay when the guards are merged or rewritten. The
                # shape-level prover stays as the sound fallback for arms whose
                # producer never claimed a partition.
                if _faces_exclusive(arm.faces, other.faces):
                    continue
                if not _are_exclusive(arm.guard, other.guard):
                    raise ExitSetFactoringGap(
                        "ExitSet.factor_completed cannot factor a completed face "
                        "whose arms are not provably exclusive.\n"
                        f"  owner: {type(arm.value).__name__} / "
                        f"{type(other.value).__name__}\n"
                        f"  arm A guard: {arm.guard!r}\n"
                        f"  arm B guard: {other.guard!r}\n"
                        "  why this is a gap: a GuardedValue chain selects ONE "
                        "face, so it can only carry a partition. Overlapping "
                        "arms with different values are two simultaneously "
                        "reachable outcomes, and collapsing them would drop one.\n"
                        "  fix: if the producing sugar OWNS a two-way split "
                        "here, mint it with outcome.exit_set.partition(owner) "
                        "and pass each face to .guarded(guard, face) — carried "
                        "testimony survives merges and rewrites that guard "
                        "shape does not. If it owns no split, these arms really "
                        "are simultaneously reachable and this gap is correct: "
                        "keep both at the exit level. Do NOT re-materialize the "
                        "product (the m ** k blow-up #6309 removed), and do NOT "
                        "widen _are_exclusive to guess exclusivity from how the "
                        "formulas are spelled.\n"
                        f"  arm A faces: {sorted(str(f) for f in arm.faces)}\n"
                        f"  arm B faces: {sorted(str(f) for f in other.faces)}",
                        arm,
                        other,
                    )

        return self._factored(completed)

    def _factored(self, completed) -> "ExitSet[T]":
        """Collapse an ADMITTED completed face into one guarded-value arm.

        One door for both admissions -- the family test and the pairwise scan --
        so the two can never drift into producing different denotations for the
        same arms. Nothing here decides admission; callers have already.
        """
        from sugar_lift_py_tests.floor import GuardedValue

        chain = completed[-1].value
        for arm in reversed(completed[:-1]):
            chain = GuardedValue(arm.guard, arm.value, chain)

        face_guard = completed[0].guard
        for arm in completed[1:]:
            face_guard = _or_guards(face_guard, arm.guard)

        # The factored arm holds under the DISJUNCTION of the arms' guards, so
        # only testimony every arm carried still holds of it. Intersection, not
        # union: a face true of one arm says nothing about the merged face.
        factored_faces = completed[0].faces
        for arm in completed[1:]:
            factored_faces = factored_faces & arm.faces

        # Obligations UNION rather than intersect. `faces` is testimony -- a
        # claim true of one arm says nothing about the merged face, so only
        # what every arm carried survives. An obligation is the opposite: it
        # was really incurred on the arm that carries it, that arm is still
        # reachable inside the factored face, and each entry is already
        # weakened under its own arm's guard, so `g_i -> D` remains exactly as
        # true of the disjunction. Intersecting here would DROP every
        # obligation any single arm owed, which is the silent-drop this whole
        # field exists to stop.
        from sugar_lift_py_tests.caller_parameter_contract import merge_pending

        factored_owed = merge_pending(*(arm.pending_contracts for arm in completed))
        factored = Completed(face_guard, chain, factored_faces, factored_owed)
        exits: list[Exit[T]] = []
        placed = False
        for exit_ in self.exits:
            if isinstance(exit_, Halted):
                exits.append(exit_)
                continue
            if not placed:
                exits.append(factored)
                placed = True
        return ExitSet(tuple(exits))

    def normalize(self) -> "ExitSet[T]":
        """Drop false exits and merge equal destinations by disjoining guards.

        The merge is indexed by destination hash, not an all-pairs scan.

        The scan was quadratic in ARM COUNT with an expensive comparison: each
        ``==`` on a callsite destination rebuilt a content coordinate. On
        ``pandas/core/generic.py`` that reached 128,462 normalize calls over
        arm sets up to 1,317 wide — an upper bound of 13,147,074 comparisons —
        to merge away 1.9% of arms. The arm counts are honest; the scan was
        not.

        This changes cost, never meaning:

        - **first-occurrence output order is preserved.** Buckets index INTO
          ``merged``; ``merged`` itself is still appended in arrival order and
          merges still write in place, so the emitted tuple is byte-identical
          to the scan's.
        - **hash never decides equality.** A bucket narrows the candidates; the
          same exact comparison as before decides, so a hash collision costs a
          comparison and nothing else.
        - **the first match still wins.** Bucket indices are appended
          ascending, so the earliest matching prior is found first, exactly as
          ``break`` did.
        - **unhashable destinations keep the old behaviour** — a full scan over
          every prior, counted in ``_UNHASHABLE_DESTINATIONS`` so the slow path
          is measured rather than silent. Nothing is dropped and nothing is
          merged that the scan would not have merged.
        """
        merged: list[Exit[T]] = []
        buckets: dict[object, list[int]] = {}
        unhashable: list[int] = []

        for exit_ in self.exits:
            if _is_false(exit_.guard):
                continue

            key = _destination_key(exit_)
            if key is _UNHASHABLE:
                # Exact previous semantics: compare against every prior.
                candidates: "list[int]" = list(range(len(merged)))
                _UNHASHABLE_DESTINATIONS.append(type(exit_).__name__)
            else:
                candidates = buckets.get(key, ())
                # An unhashable prior can still be equal to a hashable arrival
                # only if equality disagrees with hashability; compare against
                # those too rather than assume it cannot happen.
                if unhashable:
                    candidates = sorted({*candidates, *unhashable})

            for index in candidates:
                prior = merged[index]
                same_completed = (
                    isinstance(exit_, Completed)
                    and isinstance(prior, Completed)
                    and exit_.value == prior.value
                    # #6352: arms owing different obligations are different
                    # destinations on THIS face too. Merging them would keep
                    # the prior's and drop the arrival's, silently.
                    and _obligations(exit_) == _obligations(prior)
                )
                same_halted = (
                    isinstance(exit_, Halted)
                    and isinstance(prior, Halted)
                    and exit_.effect == prior.effect
                    and exit_.state == prior.state
                    # #6352: arms owing different obligations are different
                    # destinations. Merging them would keep the prior's and
                    # drop the arrival's, silently.
                    and _obligations(exit_) == _obligations(prior)
                )
                # Same destination under a DISJOINED guard. Only a split BOTH
                # contributors spoke about survives -- a partition one of them
                # never mentioned tells you nothing about where the merged arm
                # lies. For a split they both named, the merged arm lies on one
                # of their sides, so the sides UNION.
                if same_completed:
                    merged[index] = Completed(
                        _or_guards(prior.guard, exit_.guard),
                        prior.value,
                        _merge_faces(prior.faces, exit_.faces),
                        # Equal by `same_completed`; stated explicitly so the
                        # field cannot be dropped by a later edit here.
                        prior.pending_contracts,
                    )
                    break
                if same_halted:
                    merged[index] = Halted(
                        _or_guards(prior.guard, exit_.guard),
                        prior.effect,
                        prior.state,
                        _merge_faces(prior.faces, exit_.faces),
                        # Equal by `same_halted`, so this conserves rather than
                        # chooses; stated explicitly so the field cannot be
                        # dropped by a later edit to this constructor.
                        prior.pending_contracts,
                    )
                    break
            else:
                index = len(merged)
                merged.append(exit_)
                if key is _UNHASHABLE:
                    unhashable.append(index)
                else:
                    buckets.setdefault(key, []).append(index)

        return ExitSet(tuple(merged))

    def sequence(self, step: Callable[[T], "ExitSet[U]"]) -> "ExitSet[U]":
        """Map ``step`` over completed exits; halted exits bypass the tail.

        The prefix arm's obligations ride onto EVERY exit the tail produced
        under it. They were incurred before the tail ran, on the path that
        reached it, so every continuation of that path owes them -- the same
        argument that puts an obligation on ``Incomplete`` when the effect
        answers after the demand was incurred. Conjoined guards, so union:
        each side is already weakened under its own face and `g -> D` still
        holds under `g and h`. Nothing is conjoined into a single demand.
        """
        from sugar_lift_py_tests.caller_parameter_contract import merge_pending

        exits: list[Exit[U]] = []
        for exit_ in self.exits:
            if isinstance(exit_, Halted):
                exits.append(exit_)
                continue
            for following in step(exit_.value).exits:
                guard = _and_guards(exit_.guard, following.guard)
                # Conjoined guard: both sets of testimony hold of the result.
                faces = exit_.faces | following.faces
                owed = merge_pending(
                    exit_.pending_contracts, following.pending_contracts
                )
                if isinstance(following, Completed):
                    exits.append(Completed(guard, following.value, faces, owed))
                else:
                    exits.append(
                        Halted(
                            guard, following.effect, following.state, faces, owed
                        )
                    )
        return ExitSet(tuple(exits)).normalize()

    def and_then(self, step):
        return self.sequence(lambda value: outcome_to_exitset(step(value)))

    def and_finally(
        self,
        cleanup: Callable[[], "ExitSet[object]"],
        *,
        cleanup_restores: Callable[[object], bool] | None = None,
    ) -> "ExitSet[object]":
        """Run cleanup over every completed and halted exit (try/finally).

        Laws:
        - Cleanup **completion that restores** keeps the incoming exit
          (completed value or halted effect).
        - Cleanup **halt** supersedes the incoming exit.
        - Cleanup **terminal completion** (e.g. return in finally) supersedes
          with that completed value — ``cleanup_restores`` is False.

        Default: every completed cleanup restores (``cleanup_restores`` always
        True). Callers that model return-in-finally pass a predicate on the
        cleanup completed value.
        """
        restores = cleanup_restores or (lambda _value: True)
        # Construct cleanup ExitSet once; fan the same exits across every
        # incoming exit (cleanup runs on every path, not once per path).
        cleanup_exits = cleanup().exits
        # Obligations from BOTH sides ride onto every outgoing arm. The body
        # ran and the cleanup ran, so both incurred what they incurred; which
        # of the two decides the outgoing SHAPE says nothing about who owes.
        # Superseding is a choice about the exit, never a discharge.
        from sugar_lift_py_tests.caller_parameter_contract import merge_pending

        exits: list[Exit[object]] = []
        for incoming in self.exits:
            for clean in cleanup_exits:
                guard = _and_guards(incoming.guard, clean.guard)
                faces = incoming.faces | clean.faces
                owed = merge_pending(
                    incoming.pending_contracts, clean.pending_contracts
                )
                if isinstance(clean, Halted):
                    exits.append(
                        Halted(guard, clean.effect, clean.state, faces, owed)
                    )
                    continue
                if restores(clean.value):
                    if isinstance(incoming, Completed):
                        exits.append(Completed(guard, incoming.value, faces, owed))
                    else:
                        exits.append(
                            Halted(
                                guard, incoming.effect, incoming.state, faces, owed
                            )
                        )
                else:
                    # Terminal cleanup completion supersedes (return in finally).
                    exits.append(Completed(guard, clean.value, faces, owed))
        return ExitSet(tuple(exits)).normalize()

    def and_exit(
        self,
        exit_es: "ExitSet[object]",
        *,
        disposition: object,
    ) -> "ExitSet[object]":
        """Run a constructed exit over every body exit under ONE contract.

        ``exit_es`` is the already-reduced exit ExitSet (built once from tree
        sugar, not a callback). ``disposition`` is a **typed** exit contract,
        and it decides **both** edges of every incoming body exit — the
        completed edge is not pre-decided here.

        Laws:

        - Exit **halt** supersedes the incoming exit.
        - Exit **completion** hands the incoming exit — completed *or* halted —
          to ``disposition``. The outgoing exit always carries the incoming
          exit's state; the contract decides only whether it leaves as a
          completion or as a halt, and with which effect.

        A resource contract answers ``None`` on the completed edge, so a body
        that completed still completes. An assertion boundary answers with its
        unmet effect, so a body that completed halts. Both go through this one
        expression.
        """
        from sugar_lift_py_tests.outcome.exit_disposition import (
            ConsumedObservation,
            RetainedObligation,
            exit_disposition_effect,
        )

        from sugar_lift_py_tests.caller_parameter_contract import merge_pending

        def _place(target: list, guard, verdict, carried, arm_faces, owed):
            """One outgoing arm per verdict shape. Conserves the incoming arm.

            ``owed`` is the pending caller obligation this arm carries (#6392),
            threaded unchanged: authenticating an observation slot neither
            discharges an obligation nor incurs one.
            """
            if verdict is None:
                target.append(Completed(guard, carried, arm_faces, owed))
            elif isinstance(verdict, ConsumedObservation):
                # Consumed AND authenticating a slot: the testimony rides the
                # completed arm it belongs to, never a sibling arm.
                target.append(
                    Completed(
                        guard, _carry_facts(carried, verdict.facts), arm_faces, owed
                    )
                )
            else:
                target.append(Halted(guard, verdict, carried, arm_faces, owed))

        exit_exits = exit_es.exits
        exits: list[Exit[object]] = []
        for incoming in self.exits:
            for ex in exit_exits:
                guard = _and_guards(incoming.guard, ex.guard)
                faces = incoming.faces | ex.faces
                # The body ran and the exit expression ran; both sides'
                # obligations are owed on the outgoing arm. A contract decides
                # the SHAPE of the exit, never who owes what was incurred
                # reaching it -- suppression is not discharge.
                owed = merge_pending(incoming.pending_contracts, ex.pending_contracts)
                if isinstance(ex, Halted):
                    exits.append(Halted(guard, ex.effect, ex.state, faces, owed))
                    continue
                carried = (
                    incoming.value
                    if isinstance(incoming, Completed)
                    else incoming.state
                )
                verdict = exit_disposition_effect(disposition, incoming)
                if isinstance(verdict, RetainedObligation):
                    # An undecidable contract predicate is not a verdict. The
                    # incoming exit leaves as BOTH faces under complementary
                    # guards, so the predicate reaches the emitted FOL instead
                    # of being admitted or dropped by silence here.
                    #
                    # This site OWNS that split, so it mints the partition and
                    # stamps each side. The two guards are complementary by
                    # construction here; downstream must not have to rediscover
                    # that from their shape after they have been conjoined with
                    # a prefix or merged with a sibling arm.
                    obligation = verdict.obligation
                    # Owner identity is the split itself — the deciding
                    # predicate under the prefix it is decided beneath. No
                    # object identity: two runs that build the same split must
                    # agree, and a token that changes with allocation would
                    # make the testimony unreproducible.
                    held_face, failed_face = partition(
                        ("and_exit.retained_obligation", obligation, guard)
                    )
                    for sub_guard, sub_verdict, sub_face in (
                        (_and_guards(guard, obligation), verdict.held, held_face),
                        (
                            _and_guards(guard, complement_guard(obligation)),
                            verdict.failed,
                            failed_face,
                        ),
                    ):
                        # The retention narrows this arm's guard; `sub_guard`
                        # IS that narrowing, and the obligation is minted
                        # against it once, at enrolment.
                        _place(
                            exits,
                            sub_guard,
                            sub_verdict,
                            carried,
                            faces | {sub_face},
                            owed,
                        )
                    continue
                _place(exits, guard, verdict, carried, faces, owed)
        return ExitSet(tuple(exits)).normalize()


    def and_exit_truthiness(self, exit_es: "ExitSet[object]", *, site: object):
        """Run a source-constructed ``__exit__`` and retain both truth faces.

        This is the source-derived counterpart of contract-selected
        ``and_exit``.  A completed exit result is interpreted only through the
        ordinary Python truth predicate.  On an incoming halt, truth consumes
        the effect and falsity restores that exact effect; neither face is
        discarded.
        """
        from sugar_lift_py_tests.caller_parameter_contract import merge_pending
        from sugar_lift_py_tests.sugar.if_sugar import predicate_formula

        exits: list[Exit[object]] = []
        for incoming in self.exits:
            for ex in exit_es.exits:
                guard = _and_guards(incoming.guard, ex.guard)
                faces = incoming.faces | ex.faces
                owed = merge_pending(incoming.pending_contracts, ex.pending_contracts)
                if isinstance(ex, Halted):
                    exits.append(Halted(guard, ex.effect, ex.state, faces, owed))
                    continue
                if isinstance(incoming, Completed):
                    exits.append(Completed(guard, incoming.value, faces, owed))
                    continue
                from sugar_lift_py_tests.floor import TermValue

                if isinstance(ex.value, TermValue) and type(ex.value.value) is bool:
                    truth = true_guard() if ex.value.value else false_guard()
                else:
                    truth = predicate_formula(ex.value, site)
                falsity = (
                    false_guard()
                    if _is_true(truth)
                    else true_guard() if _is_false(truth) else not_(truth)
                )
                # The truth predicate is a split this site owns: exactly one of
                # truth/falsity holds. Mint it so the exclusion survives being
                # conjoined with a prefix guard downstream.
                truth_face, falsity_face = partition(
                    ("and_exit_truthiness", site, truth, guard)
                )
                exits.append(
                    Completed(
                        _and_guards(guard, truth),
                        incoming.state,
                        faces | {truth_face},
                        owed,
                    )
                )
                exits.append(
                    Halted(
                        _and_guards(guard, falsity),
                        incoming.effect,
                        incoming.state,
                        faces | {falsity_face},
                        owed,
                    )
                )
        return ExitSet(tuple(exits)).normalize()

    def collapse(self):
        """Return the old linear Outcome only for one unconditional exit.

        An arm that OWES something collapses to the linear shape that carries
        the obligation, never to the one that does not: a completed arm becomes
        the pending carrier it came from, a halted arm becomes an ``Incomplete``
        holding the same obligations. ``Complete(value)`` and
        ``Incomplete(effect)`` have no field for a demand, so returning them
        here would discharge nothing and look resolved -- the exact drop
        ``rewrap_pending`` refuses.
        """
        normalized = self.normalize()
        if len(normalized.exits) != 1 or not _is_true(normalized.exits[0].guard):
            return self if normalized == self else normalized
        exit_ = normalized.exits[0]
        if isinstance(exit_, Completed):
            if len(exit_.pending_contracts) == 1:
                # ONE pending construction: that IS the linear carrier, holding
                # this arm's value. Its demand set rides across unchanged.
                from dataclasses import replace as _replace

                return _replace(exit_.pending_contracts[0], value=exit_.value)
            if exit_.pending_contracts:
                # SEVERAL distinct pending constructions. The linear carrier
                # holds one candidate and every demand in it carries that same
                # candidate address, so two candidates have no single linear
                # shape -- fusing them would attribute one construction's
                # demands to another construction's candidate. The exit algebra
                # IS the shape that holds several, so the arm stays here. This
                # is not a gap and not a drop: collapse already answers with the
                # ExitSet whenever no linear shape denotes it.
                return normalized
            return Complete(exit_.value)
        return Incomplete(
            exit_.effect, pending_contracts=exit_.pending_contracts
        )


def sole_completed_outcome(outcome):
    """Project a body outcome onto its ONE completed arm.

    A store partitions a block into a completed and a halted arm, so a body that
    contains one reduces to an ``ExitSet`` rather than to a single linear
    ``Outcome``. A caller that is legitimately reasoning about the success path
    only -- "what does this store witness, what is the post when everything
    completed" -- uses this door.

    It REFUSES loudly when there is not exactly one completed arm, so a dropped
    success face or a silently duplicated one surfaces here instead of being
    papered over. It is not a way to discard halt arms: the halted arms are the
    other half of the meaning and are asserted by the composition laws.
    """
    if not isinstance(outcome, ExitSet):
        return outcome
    completed = [exit_ for exit_ in outcome.exits if isinstance(exit_, Completed)]
    if len(completed) != 1:
        raise ValueError(
            "sole_completed_outcome requires exactly one completed arm; got "
            f"{len(completed)} completed of {len(outcome.exits)} exits. "
            "A body with several completed faces has no single success path to "
            "project onto — reason over the ExitSet arms directly."
        )
    sole = completed[0]
    if len(sole.pending_contracts) == 1:
        # The success path still OWES what it incurred. `Complete` has no field
        # for it, so project onto the carrier instead of dropping it.
        from dataclasses import replace as _replace

        return _replace(sole.pending_contracts[0], value=sole.value)
    if sole.pending_contracts:
        raise ValueError(
            "sole_completed_outcome cannot project a completed arm owing "
            f"{len(sole.pending_contracts)} distinct pending constructions onto "
            "one linear outcome: a carrier holds ONE candidate and every demand "
            "in it carries that candidate's address, so fusing two would "
            "attribute one construction's obligations to another's candidate. "
            "Reason over the ExitSet arm directly."
        )
    return Complete(sole.value)


def factored_operand(outcome):
    """An OPERAND outcome presenting at most one completed arm (#6324).

    THE LAW THIS ENFORCES. Every k-operand fold in the lift is written the same
    way -- ``outcome = outcome.and_then(next_operand)``, k times, in
    ``collection_sugar._reduce_into``, ``method_call_sugar._collect``,
    ``bool_op_sugar``, ``fstring_sugar``. ``and_then`` is ``ExitSet.sequence``,
    and ``sequence`` appends every exit of the tail under every COMPLETED exit
    of the prefix. So an operand carrying m completed arms multiplies the
    accumulator by m, and k operands distribute into m ** k arms.

    #6319 made halting and partitioning operands LIFT instead of raising --
    correctly; that ruling drained 369 defect rows and stays. But it thereby
    put multi-arm completed faces into every one of those folds for the first
    time. The corpus measured 133,104 arms arriving at ONE ``normalize`` call
    through ``collection_sugar._reduce_into``; the file is named in #6324's
    receipt, not here -- a router must not carry a vendor spelling even in
    prose, which is what `test_routers_do_not_branch_on_keyword_vendor_or_
    manager_spelling` is watching for.

    The accumulator itself cannot be factored: its completed value is the
    growing tuple the fold is building, and a ``GuardedValue`` chain over
    tuples is not a tuple. The OPERAND can. Factoring it moves that operand's
    partition from the exit level to the value level -- one arm carrying a
    ``GuardedValue``, which is an ordinary floor value that a collection, a
    call argument, or a concatenation holds like any other. The accumulator
    then stays at one completed arm by induction from ``Complete(())``, and the
    halted arms stay at the exit level where they already grow linearly.

    Same denotation, linear growth. Nothing is capped, pruned, or dropped, and
    ``ExitSetFactoringGap`` still refuses loudly when an operand's completed
    arms are not provably pairwise exclusive.
    """
    if not isinstance(outcome, ExitSet):
        return outcome
    return outcome.factor_completed().collapse()


def outcome_to_exitset(outcome) -> ExitSet:
    if isinstance(outcome, ExitSet):
        return outcome
    if isinstance(outcome, Complete):
        return ExitSet.completed(outcome.value)
    if isinstance(outcome, Incomplete):
        # CONSERVATION AT THE CONVERSION BOUNDARY (#6352). An `Incomplete` can
        # carry obligations incurred BEFORE its effect (`o.x = p[k]` evaluates
        # `p[k]`, then the store answers). This conversion used to build the
        # halted arm from `effect` alone, so those obligations vanished HERE --
        # silently, on a boundary, where nothing downstream could report them.
        # A demand that disappears at an effect -> halted conversion is
        # unattributable afterward: no caller owes it and no instrument knows.
        #
        # They cross AS INCURRED. The arm's own guard is the face they are owed
        # on, and `guard -> D` is minted once, at the block boundary that enrols
        # them. Weakening here as well would mint the same implication twice
        # over -- and every re-mint is a new `demand_cid`, which is a new
        # destination, which stops the arm merging in `normalize`.
        contracts = tuple(getattr(outcome, "pending_contracts", ()))
        if outcome.branch_conditions:
            guard = and_(list(outcome.branch_conditions))
            return ExitSet(
                (
                    Halted(
                        guard,
                        outcome.effect,
                        None,
                        pending_contracts=contracts,
                    ),
                )
            ).normalize()
        return ExitSet(
            (
                Halted(
                    true_guard(),
                    outcome.effect,
                    None,
                    pending_contracts=contracts,
                ),
            )
        ).normalize()

    # A PENDING PARAMETER-CONTRACT CARRIER (#6352). This USED to panic: the exit
    # algebra had no arm that wrapped a value together with an undischarged
    # obligation, so the only honest answer was a named gap.
    #
    # `Completed.pending_contracts` is that arm. The carrier converts to one
    # unconditional completed exit holding the carried value and owing exactly
    # what the carrier owed -- the same conversion `Incomplete` gets, on the
    # other face. Nothing is hoisted, nothing is dropped, and the round trip
    # back through `collapse` returns the carrier.
    from sugar_lift_py_tests.caller_parameter_contract import (
        ContractConditionalConstructionV1,
    )
    from sugar_lift_py_tests.gap.info import GapKind
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    if isinstance(outcome, ContractConditionalConstructionV1):
        return ExitSet(
            (
                Completed(
                    true_guard(),
                    outcome.value,
                    pending_contracts=(outcome,),
                ),
            )
        ).normalize()

    construction_panic_gap(
        owner="outcome_to_exitset",
        blame=type(outcome).__name__,
        observed=f"{type(outcome).__name__} is not an Outcome the exit algebra knows",
        requested="Complete, Incomplete or ExitSet",
        fix=(
            "give this outcome variant an arm in `outcome_to_exitset`, or stop "
            "producing it upstream of the exit algebra"
        ),
        gap_kind=GapKind.FLOOR,
    )


__all__ = [
    "Completed",
    "ExitSet",
    "ExitSetFactoringGap",
    "PartitionFace",
    "partition",
    "Halted",
    "complement_guard",
    "factored_operand",
    "false_guard",
    "sole_completed_outcome",
    "true_guard",
    "outcome_to_exitset",
]


def _carry_facts(carried, facts: tuple):
    """Splice authenticated facts into the state the outgoing arm carries.

    Same shape as the Try handler's binding deposit: a reduced block gets the
    facts spliced into its entries, anything else is wrapped once so the
    testimony has somewhere to live. No arm is added and none is dropped.
    """
    from dataclasses import replace as _replace

    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    if not facts:
        return carried
    if isinstance(carried, _ReducedBlock):
        return _replace(carried, entries=(*facts, *carried.entries))
    return _ReducedBlock(
        entries=(*facts, carried) if carried is not None else facts,
        can_fall_through=True,
        fall_through=(),
    )
