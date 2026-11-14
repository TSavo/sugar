"""Guarded block exits: the effect-dimension phi for statement sequencing."""

from __future__ import annotations

import weakref
from dataclasses import dataclass, field as _dataclass_field
from typing import Callable, Generic, TypeVar

from sugar_lift_py_tests.effect import Effect, require_effect
from sugar_lift_py_tests.ir import Formula, _Connective, and_, not_, or_

T = TypeVar("T")
U = TypeVar("U")


def true_guard() -> Formula:
    """The existing FOL encoding of truth: an empty conjunction."""
    return and_([])


def false_guard() -> Formula:
    return not_(true_guard())


def _is_true(guard: Formula) -> bool:
    # Content equality with ``and_([])`` read off the shape: a formula's
    # content key is ("connective", kind, operand keys), so it equals the
    # empty conjunction exactly when it IS an operand-less "and" connective.
    # Comparing against a freshly built guard authenticated the whole guard
    # DAG's content identity on every call (#7664).
    return type(guard) is _Connective and guard.kind == "and" and not guard.operands


def _is_false(guard: Formula) -> bool:
    # Content equality with ``not_(and_([]))``, read off the shape.
    return (
        type(guard) is _Connective
        and guard.kind == "not"
        and len(guard.operands) == 1
        and _is_true(guard.operands[0])
    )


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


def partition_family(owner: object, sides: tuple) -> tuple[PartitionFace, ...]:
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
    return frozenset(face for face in (left | right) if face.partition in shared)


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


def _assigned_rows(value) -> tuple:
    """The assignment values a completed block's context records."""
    context = getattr(value, "context", None)
    return getattr(context, "assigned_values", ()) or ()


def _same_evaluations(left, right) -> bool:
    """Whether two completed blocks' contexts hold every statement
    evaluation (``TemporalContext.evaluations``) at one value."""
    left_temporal = getattr(getattr(left, "context", None), "temporal", None)
    right_temporal = getattr(getattr(right, "context", None), "temporal", None)
    if left_temporal is right_temporal:
        return True
    return _evaluation_rows(left_temporal) == _evaluation_rows(right_temporal)


def _evaluation_rows(temporal) -> dict:
    """The statement evaluations ``temporal`` holds, by key."""
    evaluations = getattr(temporal, "evaluations", None)
    if evaluations is None:
        return {}
    return {binding.name: binding.value for binding in evaluations()}


# Identity-retained destination hashes (#7664).  A frozen dataclass's hash is a
# function of its content, which cannot change, so one live object hashes the
# same forever.  ``normalize`` re-buckets the same arm values on every call
# (pinned pandas ``tests/io/pytables/test_subclass.py``: 1.67M destination
# keys, 95M recursive dataclass ``__hash__`` frames), and a dataclass does not
# cache its hash.  Retained per live object under a weakref guard, so a dead
# object's recycled ``id`` never answers for a new one; a value that cannot be
# weakly referenced (a tuple, an int) is hashed directly, as before.  A
# ``TypeError`` is never retained: unhashable stays unhashable on every call.
_DESTINATION_HASH: dict[int, tuple["weakref.ReferenceType", int]] = {}


def _retained_hash(value: object) -> int:
    vid = id(value)
    entry = _DESTINATION_HASH.get(vid)
    if entry is not None:
        if entry[0]() is value:
            return entry[1]
        _DESTINATION_HASH.pop(vid, None)
    hashed = hash(value)
    params = getattr(type(value), "__dataclass_params__", None)
    if params is None or not params.frozen:
        # Only a FROZEN dataclass's content hash is known not to drift; any
        # other ``__hash__`` is asked fresh every time, exactly as before.
        return hashed
    try:
        def _on_die(wr: "weakref.ReferenceType", *, _vid: int = vid) -> None:
            current = _DESTINATION_HASH.get(_vid)
            if current is not None and current[0] is wr:
                _DESTINATION_HASH.pop(_vid, None)

        _DESTINATION_HASH[vid] = (weakref.ref(value, _on_die), hashed)
    except TypeError:
        pass
    return hashed


def _destination_key(exit_: "Exit[T]") -> object:
    """Bucket key for an exit's DESTINATION, ignoring its guard.

    Two exits merge exactly when their destinations are equal, so the guard —
    the thing the merge rewrites — must not enter the key. Returns
    ``_UNHASHABLE`` when the destination cannot be hashed.
    """
    try:
        if isinstance(exit_, Completed):
            return ("completed", _retained_hash(exit_.value))
        return (
            "halted",
            _retained_hash(exit_.effect),
            _retained_hash(exit_.state),
        )
    except TypeError:
        return _UNHASHABLE


_NO_OWED: tuple = ()


def _owed_union(*parts: tuple) -> tuple:
    """Every owed item of every contributor, once, in first-seen order.

    THE RULE FOR ``owed`` AT EVERY ARM REBUILD. An arm owes what any path
    into it incurred, so a rebuild from one arm keeps that arm's ``owed``, and
    a rebuild from several (a merge, a sequence, a fan) owes the union. Never
    an intersection: unlike ``faces``, which is testimony that weakens when
    arms merge, an owed item is a debt, and a merged arm owes every debt of
    every arm it stands for. Dropping one is dropping a member of the proof.

    Private (#7825): only the rebuilds in this module call it. Outside it, a
    step and what follows compose through ``ExitSet.sequence`` (``consume=``
    for a halt the composition owns), arms that stand for each other merge
    through ``ExitSet.union`` / ``normalize``, and the debts of a set of arms
    are read with ``ExitSet.owed_items``. Nobody else unions debts by hand.
    """
    nonempty = [part for part in parts if part]
    if not nonempty:
        return _NO_OWED
    if len(nonempty) == 1:
        return tuple(nonempty[0])
    merged = list(nonempty[0])
    for part in nonempty[1:]:
        for item in part:
            if item not in merged:
                merged.append(item)
    return tuple(merged)


@dataclass(frozen=True)
class Completed(Generic[T]):
    """Control left with this value, under this guard."""

    guard: Formula
    value: T
    # Testimony ABOUT this arm, never part of what it denotes: two arms with the
    # same guard and destination are the same exit whether or not a producer
    # stamped them. Excluded from compare/repr so carrying testimony cannot
    # perturb exit equality, normalize's merge, or any golden repr.
    faces: frozenset[PartitionFace] = _dataclass_field(
        default=_NO_FACES, compare=False, repr=False
    )
    # What this arm OWES (#7825, H4): items the proof must carry as members
    # because something on a path into this arm left them unanswered (today:
    # ``unanswered_calls.UnansweredCallV1``). Like ``faces`` it is not part of
    # what the arm denotes, so it is excluded from compare/hash/repr: it never
    # decides a merge in ``normalize``, never enters a destination key, never
    # enters an enrolled CID. Unlike ``faces`` it is carried by UNION at every
    # rebuild (``_owed_union``).
    owed: tuple = _dataclass_field(default=_NO_OWED, compare=False, repr=False)


@dataclass(frozen=True)
class Halted:
    """Control left with this effect, under this guard, from this state."""

    guard: Formula
    effect: Effect
    state: object | None = None
    faces: frozenset[PartitionFace] = _dataclass_field(
        default=_NO_FACES, compare=False, repr=False
    )
    # See ``Completed.owed``: a halted arm owes what the path that reached
    # the halt incurred, exactly as a completed one does.
    owed: tuple = _dataclass_field(default=_NO_OWED, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect", require_effect(self.effect))


Exit = Completed[T] | Halted


@dataclass(frozen=True)
class ExitSet(Generic[T]):
    """A partition of reachable execution into completed and halted exits."""

    exits: tuple[Exit[T], ...]

    @classmethod
    def completed(
        cls, value: T, guard: Formula | None = None, *, owed: tuple = _NO_OWED
    ) -> "ExitSet[T]":
        """One completed arm holding ``v`` under ``guard`` (truth when omitted),
        owing ``owed`` (nothing when omitted)."""
        return cls((Completed(guard or true_guard(), value, owed=owed),)).normalize()

    @classmethod
    def halted(
        cls, effect: Effect, guard: Formula | None = None, state=None
    ) -> "ExitSet[T]":
        """One halted arm with ``effect`` under ``guard`` (truth when omitted),
        from ``state``. A halt under several branch conditions is
        ``ExitSet.halted(e, guard=and_([c1, ..., cn]))``.
        """
        return cls((Halted(guard or true_guard(), effect, state),)).normalize()

    @classmethod
    def two_faced(
        cls,
        value: T,
        raise_effect: Effect,
        *,
        guard: Formula,
        site,
        symbol: str | None = None,
        owed: tuple = _NO_OWED,
        state: object | None = None,
    ) -> "ExitSet[T]":
        """Completes with ``value``, or raises something undetermined.

        THE ONE CONSTRUCTOR of the two-faced outcome (#7757 item 13). An
        operation whose body was not looked at (an unprojected call, an
        undecided operand's dunder, a formal-selected manager step, an opaque
        attribute or subscript, a native operation its caller left without an
        actual, a store over an undecided receiver, an unpack of a value with
        no authenticated cardinality) completes with ``value`` only under its
        ``guard`` -- the
        site-keyed ``...completes`` atom -- and halts with ``raise_effect`` (an
        ``UndeterminedRaiseEffect``) from ``state`` (none unless the producer
        holds the state the operation began from) under
        ``complement_guard(guard)``. Nobody assembles this pair by hand.

        What the operation does is not decided here, and the one way to say
        so is the ``undecided`` member (reason ``unanswered``). So this
        constructor itself attaches that debt: both arms owe
        ``unanswered_call(symbol, site)`` -- ``site`` the operation's source
        fragment (or its coordinate), ``symbol`` the one import table's
        target symbol when the operation is an import-bound call, else none
        (Q5) -- after ``owed``, what the path into the operation already
        owed. Both arms, because the debt is incurred whether the operation
        completes or raises. No producer can build the pair and forget it.
        """
        from sugar_lift_py_tests.unanswered_calls import unanswered_call

        debts = _owed_union(owed, (unanswered_call(symbol, site),))
        return cls(
            (
                Completed(guard, value, owed=debts),
                Halted(complement_guard(guard), raise_effect, state, owed=debts),
            )
        ).normalize()

    def completed_value(self):
        """The single unconditional completed value, else ``None``.

        Answers a value exactly when the set is ONE completed arm under
        truth. A guarded completion, a second arm, or any
        halt answers ``None``: there is no single success value to hand over,
        and the caller reasons over the arms instead. ``owed`` does not enter:
        it is not part of what the arm denotes.
        """
        normalized = self.normalize()
        if len(normalized.exits) != 1:
            return None
        exit_ = normalized.exits[0]
        if isinstance(exit_, Completed) and _is_true(exit_.guard):
            return exit_.value
        return None

    def halts(self) -> tuple[Halted, ...]:
        """The halted arms, in order.

        Every arm halts exactly when ``o.halts() == o.exits``; "can this
        halt" is ``bool(o.halts())``. A guarded halt keeps its guard on the
        arm (``h.guard``).
        """
        return tuple(exit_ for exit_ in self.exits if isinstance(exit_, Halted))

    def owed_items(self) -> tuple:
        """Every item any arm owes, once, in first-seen order (``_owed_union``).

        The reader of the owed slot: a consumer that packages members reads
        them off the FINAL set of arms, never off a side channel. It is also
        the one join of debts across sibling arms: a caller that needs what a
        set of arms owes together reads it here, never by unioning by hand.
        """
        return _owed_union(*(exit_.owed for exit_ in self.exits))

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

    def union(self, *others: "ExitSet[T]") -> "ExitSet[T]":
        """THE JOIN of sibling exit sets: every arm of each, in order, merged
        once by ``normalize`` (equal destinations disjoin their guards and owe
        every debt). Any number of siblings join in one call, so a join of
        many never re-normalizes the arms gathered so far. Nobody concatenates
        arm lists by hand (#7825)."""
        return ExitSet(
            (*self.exits, *(exit_ for other in others for exit_ in other.exits))
        ).normalize()

    def guarded(
        self, guard: Formula, face: PartitionFace | None = None
    ) -> "ExitSet[T]":
        """Restrict every exit to one branch of an enclosing partition.

        ``face`` is the caller's testimony that ``guard`` is one named side of a
        split it owns (see ``partition``). It rides along on every restricted
        exit so that a later ``factor_completed`` can read the exclusion off the
        arms instead of trying to re-prove it from guard shape. Omitting it is
        the honest default for a restriction that is not a partition face.

        """
        exits: list[Exit[T]] = []
        for exit_ in self.exits:
            combined = _and_guards(guard, exit_.guard)
            faces = exit_.faces if face is None else exit_.faces | {face}
            if isinstance(exit_, Completed):
                exits.append(Completed(combined, exit_.value, faces, exit_.owed))
            else:
                exits.append(
                    Halted(combined, exit_.effect, exit_.state, faces, exit_.owed)
                )
        return ExitSet(tuple(exits)).normalize()

    def with_partition_face(self, partition_id: object, face: int) -> "ExitSet[T]":
        """Stamp every completed arm with one face of ``partition(partition_id)``.

        Face is 0/1 for then/else of one producer-owned branch: the then and
        else faces ``partition`` mints for that owner. The stamp joins the
        arm's ``faces`` (it never replaces them), so nested joins accumulate
        faces and two arms are exclusive when they lie on different sides of a
        shared split (``_faces_exclusive``). Halted arms stand unchanged. The
        stamp is a continuation beneath each completed arm, so every arm keeps
        its guard and ``owed``.
        """
        stamp = partition(partition_id)[face]
        return self.sequence(
            lambda value: ExitSet.completed(value).guarded(true_guard(), stamp)
        )

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

        # Owed is the opposite: the factored arm stands for every arm, so it
        # owes every arm's debt.
        factored = Completed(
            face_guard,
            chain,
            factored_faces,
            _owed_union(*(arm.owed for arm in completed)),
        )
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
                    # Arms that completed an assignment with different values
                    # (``y = -x if c else 0``) hold equal records but different
                    # recorded values: merging them would keep the prior's
                    # value on both paths.
                    and _assigned_rows(exit_.value) == _assigned_rows(prior.value)
                    # Arms that bound one statement evaluation to different
                    # values (a loop left by its ``break`` on one path and
                    # by exhaustion on another) are two paths: merged, the
                    # prior's value would be read on both, and the other's
                    # dropped.  Every evaluation key, one rule.
                    and _same_evaluations(exit_.value, prior.value)
                )
                same_halted = (
                    isinstance(exit_, Halted)
                    and isinstance(prior, Halted)
                    and exit_.effect == prior.effect
                    and exit_.state == prior.state
                    # A halt's record (a ``break``/``continue``'s included,
                    # whose context the loop reads its latch from) is the
                    # same path only where its context holds every statement
                    # evaluation at one value: the rule completed arms keep.
                    and _same_evaluations(exit_.state, prior.state)
                )
                # Same destination under a DISJOINED guard. Only a split BOTH
                # contributors spoke about survives -- a partition one of them
                # never mentioned tells you nothing about where the merged arm
                # lies. For a split they both named, the merged arm lies on one
                # of their sides, so the sides UNION.
                # ``owed`` never decides the merge (it is not in the key or the
                # comparison above); the merged arm owes both contributors'.
                if same_completed:
                    merged[index] = Completed(
                        _or_guards(prior.guard, exit_.guard),
                        prior.value,
                        _merge_faces(prior.faces, exit_.faces),
                        _owed_union(prior.owed, exit_.owed),
                    )
                    break
                if same_halted:
                    merged[index] = Halted(
                        _or_guards(prior.guard, exit_.guard),
                        prior.effect,
                        prior.state,
                        _merge_faces(prior.faces, exit_.faces),
                        _owed_union(prior.owed, exit_.owed),
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

    def sequence(
        self,
        step: Callable[[T], "ExitSet[U]"],
        *,
        consume: Callable[[Halted], "ExitSet[U] | None"] | None = None,
    ) -> "ExitSet[U]":
        """Map ``step`` over completed exits; halted exits bypass the tail.

        The prefix arm's obligations ride onto EVERY exit the tail produced
        under it. They were incurred before the tail ran, on the path that
        reached it, so every continuation of that path owes them -- the same
        argument that puts an obligation on a halted arm when the effect
        answers after the demand was incurred. Conjoined guards, so union:
        each side is already weakened under its own face and `g -> D` still
        holds under `g and h`. Nothing is conjoined into a single demand.

        ``consume`` is for a composition that continues past a halt it owns
        (a loop's own ``break``/``continue``, the ``StopIteration`` that
        exhausts its iterator). It is handed each halted arm and answers the
        set that continues beneath that halt, or ``None`` to let the halt
        stand. A consumed halt's continuation is composed exactly as a
        completed arm's is: conjoined guard, both sets of faces, and the
        halt's ``owed`` first. This is the one composition of a continuation
        beneath an arm; there is no second way to carry a prefix's debts.

        A step or ``consume`` that answers a deferred native-operation carrier
        (a loop or ``with`` body still waiting on its caller's actual) is
        composed through the carrier's own ``after_discharge``, as
        ``and_then`` hands one on: once it discharges, its exits are composed
        beneath that arm exactly as an ``ExitSet``'s are, beside every other
        arm's continuation in arm order, and the answer is that carrier.
        Anything else that is not an ``ExitSet`` cannot compose and is refused
        by name (``_require_exit_set``, owner ``ExitSet.sequence``).
        """

        exits: list[Exit[U]] = []
        deferred: list | None = None
        for exit_ in self.exits:
            if isinstance(exit_, Halted):
                continued = None if consume is None else consume(exit_)
                if continued is None:
                    exits.append(exit_)
                    continue
            else:
                continued = step(exit_.value)
            if isinstance(continued, ExitSet):
                _extend_beneath(exits, exit_, continued)
                continue
            # Where this arm's continuation goes once its carrier discharges:
            # after every arm already composed, before every later one.
            if deferred is None:
                deferred = []
            deferred.append((len(exits), exit_, _carrier_or_refuse(continued)))
        if deferred is None:
            return ExitSet(tuple(exits)).normalize()
        return _compose_after_discharge(tuple(exits), tuple(deferred))

    def and_then(self, step):
        """Run ``step`` on every completed arm's value; halts bypass it.

        This is ``sequence`` per arm, with each arm's guard, faces and
        ``owed`` carried onto what ``step`` produced under it.

        Over ONE plain arm (truth, no faces, owing nothing) it is exactly
        ``step(v)``, including when ``step`` answers a deferred
        native-operation carrier: that carrier is handed on. Over any other
        shape a carrier, or anything else that is not an ``ExitSet``, is
        refused by name (``_require_exit_set``).
        """
        if (
            len(self.exits) == 1
            and isinstance(self.exits[0], Completed)
            and _is_true(self.exits[0].guard)
            and not self.exits[0].faces
            and not self.exits[0].owed
        ):
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )

            following = step(self.exits[0].value)
            if isinstance(following, NativeOperationExitCarrierV1):
                return following
            return self.sequence(lambda _value: _require_exit_set(following))
        return self.sequence(lambda value: _require_exit_set(step(value)))

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

        exits: list[Exit[object]] = []
        for incoming in self.exits:
            for clean in cleanup_exits:
                guard = _and_guards(incoming.guard, clean.guard)
                faces = incoming.faces | clean.faces
                owed = _owed_union(incoming.owed, clean.owed)
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

        def _place(target: list, guard, verdict, carried, arm_faces, arm_owed):
            """One outgoing arm per verdict shape. Conserves the incoming arm."""
            if verdict is None:
                target.append(Completed(guard, carried, arm_faces, arm_owed))
            elif isinstance(verdict, ConsumedObservation):
                # Consumed AND authenticating a slot: the testimony rides the
                # completed arm it belongs to, never a sibling arm.
                target.append(
                    Completed(
                        guard,
                        _carry_facts(carried, verdict.facts),
                        arm_faces,
                        arm_owed,
                    )
                )
            else:
                target.append(Halted(guard, verdict, carried, arm_faces, arm_owed))

        exit_exits = exit_es.exits
        exits: list[Exit[object]] = []
        for incoming in self.exits:
            for ex in exit_exits:
                guard = _and_guards(incoming.guard, ex.guard)
                faces = incoming.faces | ex.faces
                owed = _owed_union(incoming.owed, ex.owed)
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
                        # IS that narrowing.
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
        from sugar_lift_py_tests.sugar.if_sugar import predicate_formula

        exits: list[Exit[object]] = []
        for incoming in self.exits:
            for ex in exit_es.exits:
                guard = _and_guards(incoming.guard, ex.guard)
                faces = incoming.faces | ex.faces
                owed = _owed_union(incoming.owed, ex.owed)
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


def _extend_beneath(target: list, prefix: Exit, continued: ExitSet) -> None:
    """Append ``continued``'s arms as the continuation beneath ``prefix``.

    The one composition ``sequence`` performs per arm, whether the
    continuation was answered at once or after a carrier discharged.
    """
    for following in continued.exits:
        guard = _and_guards(prefix.guard, following.guard)
        # Conjoined guard: both sets of testimony hold of the result.
        faces = prefix.faces | following.faces
        # The prefix's debts ride onto every continuation of its path.
        owed = _owed_union(prefix.owed, following.owed)
        if isinstance(following, Completed):
            target.append(Completed(guard, following.value, faces, owed))
        else:
            target.append(Halted(guard, following.effect, following.state, faces, owed))


def _carrier_or_refuse(outcome):
    """A deferred native-operation carrier ``sequence`` can compose, or the
    refusal of anything else that is not an ``ExitSet``."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    if isinstance(outcome, NativeOperationExitCarrierV1):
        return outcome
    return _require_exit_set(outcome, owner="ExitSet.sequence")


def _compose_after_discharge(resolved: tuple, deferred: tuple):
    """``sequence``'s answer when arms' continuations wait on carriers.

    ``resolved`` holds every arm composed already; each ``deferred`` entry is
    ``(position, prefix arm, carrier)``, its position the slot in
    ``resolved`` its continuation fills. The first carrier composes the
    rest through its ``after_discharge`` (``_SequencedBeside``): once it
    discharges, its exits go beneath their prefix arm at that slot, and a
    later carrier answered from there is discharged by the same caller in
    turn (``discharge`` discharges a carrier an ``after_discharge`` step
    answers). A carrier whose caller has no actual still discharges, to its
    cited unanswered face, so every resolved arm stands (#7825).
    """
    position, prefix, carrier = deferred[0]
    return carrier.after_discharge(
        _SequencedBeside(resolved, position, prefix, deferred[1:])
    )


@dataclass(frozen=True, eq=False)
class _SequencedBeside:
    """The step that composes a carrier's exits beside ``sequence``'s arms.

    ``resolved`` is every arm ``sequence`` composed already, ``position``
    the slot the carrier's exits fill beneath ``prefix``, and ``rest`` the
    later ``(position, prefix arm, carrier)`` entries still waiting. It is
    a value, not a closure, so a reader of what a deferred outcome already
    reduced reads its arms (``NativeOperationExitCarrierV1.composed_beside``).
    """

    resolved: tuple
    position: int
    prefix: object
    rest: tuple

    def __call__(self, projected):
        inserted: list = []
        _extend_beneath(
            inserted,
            self.prefix,
            _require_exit_set(projected, owner="ExitSet.sequence"),
        )
        composed = (
            *self.resolved[: self.position],
            *inserted,
            *self.resolved[self.position :],
        )
        if not self.rest:
            return ExitSet(composed).normalize()
        shift = len(inserted)
        return _compose_after_discharge(
            composed,
            tuple((later + shift, arm, waiting) for later, arm, waiting in self.rest),
        )


def sole_completed_value(outcome: ExitSet):
    """The value of a body outcome's ONE completed arm.

    A store partitions a block into a completed and a halted arm, so a body
    that contains one reduces to several arms. A caller that is legitimately
    reasoning about the success path only -- "what does this store witness,
    what is the post when everything completed" -- uses this door.

    It REFUSES loudly when there is not exactly one completed arm, so a dropped
    success face or a silently duplicated one surfaces here instead of being
    papered over. It is not a way to discard halt arms: the halted arms are the
    other half of the meaning and are asserted by the composition laws.
    """
    completed = [exit_ for exit_ in outcome.exits if isinstance(exit_, Completed)]
    if len(completed) != 1:
        raise ValueError(
            "sole_completed_value requires exactly one completed arm; got "
            f"{len(completed)} completed of {len(outcome.exits)} exits. "
            "A body with several completed faces has no single success path to "
            "project onto — reason over the ExitSet arms directly."
        )
    return completed[0].value


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
    then stays at one completed arm by induction from ``ExitSet.completed(())``, and the
    halted arms stay at the exit level where they already grow linearly.

    Same denotation, linear growth. Nothing is capped, pruned, or dropped, and
    ``ExitSetFactoringGap`` still refuses loudly when an operand's completed
    arms are not provably pairwise exclusive.

    The factored operand stays an ``ExitSet``. A
    deferred native-operation carrier is not an ``ExitSet`` and passes through
    as itself, which is why the operand folds call this door rather than
    ``factor_completed`` directly.
    """
    if not isinstance(outcome, ExitSet):
        return outcome
    return outcome.factor_completed()


def _require_exit_set(outcome, *, owner: str = "ExitSet.and_then") -> ExitSet:
    """The one refusal of something that is not exits where exits are needed.

    ``and_then`` refuses a step that answered something else; every position
    that reads an outcome's arms directly (``.exits``, ``completed_value()``,
    ``sequence``) and cannot hand a deferred carrier on through the carrier's
    own ``and_then`` / ``after_discharge`` refuses through here too, under its
    own ``owner``. ``ExitSet.sequence`` composes a carrier a step answers and
    refuses anything else here (owner ``ExitSet.sequence``).

    Not a conversion: an ``ExitSet`` is handed back as itself and nothing
    else is ever turned into one. A deferred native-operation carrier is
    refused as the undischarged demand it is; anything else by its type.
    """
    if isinstance(outcome, ExitSet):
        return outcome

    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.gap.info import GapKind
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    if isinstance(outcome, NativeOperationExitCarrierV1):

        construction_panic_gap(
            owner=owner,
            blame=outcome.demand.source_node,
            observed=(
                "undischarged native operation demand: "
                f"{type(outcome).__name__} demand="
                f"{type(outcome.demand).__name__}"
            ),
            requested=(
                "an ExitSet projected from authenticated caller actual operands"
            ),
            fix=(
                "retain the carrier through caller discharge; do not treat the "
                "absence of a halted edge as normal completion"
            ),
            gap_kind=GapKind.FLOOR,
        )

    construction_panic_gap(
        owner=owner,
        blame=type(outcome).__name__,
        observed=f"{type(outcome).__name__} is not an ExitSet",
        requested="ExitSet",
        fix="answer an ExitSet from the step",
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
    "sole_completed_value",
    "true_guard",
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
