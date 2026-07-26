"""Guarded block exits: the effect-dimension phi for statement sequencing."""

from __future__ import annotations

import logging
from dataclasses import dataclass
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


_LOGGER = logging.getLogger("sugar_lift_py_tests.exit_set")

# Sentinel for a destination that cannot be hashed. A distinct object rather than
# ``None``, because ``None`` is a perfectly good destination key.
_UNHASHABLE = object()


@dataclass
class _NormalizeStats:
    """Measured fallback: normalization is observable, not assumed.

    The bucketed normalizer's whole claim is that comparisons stop scaling with
    the square of the arm count. A claim like that has to be measurable from
    outside or it decays into folklore the first time someone adds a destination
    type that does not hash.
    """

    calls: int = 0
    arms: int = 0
    comparisons: int = 0
    unhashable_destinations: int = 0
    _warned: bool = False

    def record(self, *, arms: int, comparisons: int, unhashable: int) -> None:
        self.calls += 1
        self.arms += arms
        self.comparisons += comparisons
        self.unhashable_destinations += unhashable
        if unhashable and not self._warned:
            # LOUD, once per process: an unhashable destination silently degrades
            # this back toward the all-pairs scan it replaced. Nothing is dropped
            # and no merge is missed -- but the performance claim no longer holds,
            # and that is worth saying rather than discovering in a timeout.
            self._warned = True
            _LOGGER.warning(
                "ExitSet.normalize: %d unhashable destination(s); those exits fall "
                "back to a full scan. Merges are still exact; comparisons are not "
                "bucket-local for them.",
                unhashable,
            )

    def reset(self) -> None:
        self.calls = 0
        self.arms = 0
        self.comparisons = 0
        self.unhashable_destinations = 0
        self._warned = False


_NORMALIZE_STATS = _NormalizeStats()


def normalize_stats() -> _NormalizeStats:
    """The live normalization counters, for scaling receipts and gates."""
    return _NORMALIZE_STATS


def _destination_key(exit_: "Exit[T]") -> object:
    """A hash coordinate for an exit's DESTINATION -- never its guard.

    Guards are what merging disjoins, so two exits to the same destination differ
    precisely in their guards; keying on the guard would put them in different
    buckets and defeat the merge. The class tag keeps a ``Completed`` value from
    colliding with a ``Halted`` ``(effect, state)`` pair of the same shape.
    """
    if isinstance(exit_, Completed):
        key: object = (Completed, exit_.value)
    else:
        key = (Halted, exit_.effect, exit_.state)
    try:
        hash(key)
    except TypeError:
        return _UNHASHABLE
    return key


@dataclass(frozen=True)
class Completed(Generic[T]):
    guard: Formula
    value: T


@dataclass(frozen=True)
class Halted:
    guard: Formula
    effect: Effect
    state: object | None = None

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
        return cls(
            (Halted(guard, effect, state), Completed(not_(guard), state))
        ).normalize()

    def union(self, other: "ExitSet[T]") -> "ExitSet[T]":
        return ExitSet((*self.exits, *other.exits)).normalize()

    def guarded(self, guard: Formula) -> "ExitSet[T]":
        """Restrict every exit to one branch of an enclosing partition."""
        exits: list[Exit[T]] = []
        for exit_ in self.exits:
            combined = _and_guards(guard, exit_.guard)
            if isinstance(exit_, Completed):
                exits.append(Completed(combined, exit_.value))
            else:
                exits.append(Halted(combined, exit_.effect, exit_.state))
        return ExitSet(tuple(exits)).normalize()

    def normalize(self) -> "ExitSet[T]":
        """Drop false exits and merge equal destinations by disjoining guards.

        Indexed by DESTINATION HASH BUCKET, not by scanning every prior exit.
        The old all-pairs scan was quadratic in arm count -- at ~775 arms that is
        ~600k destination comparisons -- which is what put `core/generic.py` over
        the timeout floor.

        The bucket key is a hash coordinate only. **A collision is a collision,
        never equality**: the exact comparison below still decides every merge, so
        this changes the number of comparisons and nothing about which exits merge.
        Equal destinations land in the same bucket because Python's hash/eq
        contract guarantees equal objects hash equal -- that is what makes
        bucket-local comparison complete rather than merely cheaper.

        Order is preserved by construction: buckets hold INDICES into ``merged``,
        candidates are visited in ascending index order, and a merge rewrites in
        place at the first-occurrence position. So output order is first-occurrence
        order, exactly as the scan produced.
        """
        merged: list[Exit[T]] = []
        # destination key -> indices into `merged`, ascending.
        buckets: dict[object, list[int]] = {}
        # Destinations that cannot be hashed. These are NOT dropped and NOT assumed
        # distinct: they stay in a scanned list, and every exit is compared against
        # them as well as against its own bucket. Without that, a hashable exit
        # equal to an unhashable prior would silently fail to merge -- a wrong
        # answer, not a slow one. Cost degrades only with the number of unhashable
        # destinations, and the count is reported below.
        unhashable: list[int] = []
        comparisons = 0
        for exit_ in self.exits:
            if _is_false(exit_.guard):
                continue
            key = _destination_key(exit_)
            if key is _UNHASHABLE:
                # Exact semantics demand a full scan here: an unhashable value may
                # still compare equal to a hashable one, and only comparison knows.
                candidates: list[int] = list(range(len(merged)))
            elif unhashable:
                candidates = sorted(buckets.get(key, []) + unhashable)
            else:
                candidates = buckets.get(key, [])
            for index in candidates:
                prior = merged[index]
                comparisons += 1
                same_completed = (
                    isinstance(exit_, Completed)
                    and isinstance(prior, Completed)
                    and exit_.value == prior.value
                )
                same_halted = (
                    isinstance(exit_, Halted)
                    and isinstance(prior, Halted)
                    and exit_.effect == prior.effect
                    and exit_.state == prior.state
                )
                if same_completed:
                    merged[index] = Completed(
                        _or_guards(prior.guard, exit_.guard), prior.value
                    )
                    break
                if same_halted:
                    merged[index] = Halted(
                        _or_guards(prior.guard, exit_.guard), prior.effect, prior.state
                    )
                    break
            else:
                index = len(merged)
                merged.append(exit_)
                if key is _UNHASHABLE:
                    unhashable.append(index)
                else:
                    buckets.setdefault(key, []).append(index)
        _NORMALIZE_STATS.record(
            arms=len(self.exits), comparisons=comparisons, unhashable=len(unhashable)
        )
        return ExitSet(tuple(merged))

    def sequence(self, step: Callable[[T], "ExitSet[U]"]) -> "ExitSet[U]":
        """Map ``step`` over completed exits; halted exits bypass the tail."""
        exits: list[Exit[U]] = []
        for exit_ in self.exits:
            if isinstance(exit_, Halted):
                exits.append(exit_)
                continue
            for following in step(exit_.value).exits:
                guard = _and_guards(exit_.guard, following.guard)
                if isinstance(following, Completed):
                    exits.append(Completed(guard, following.value))
                else:
                    exits.append(Halted(guard, following.effect, following.state))
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
        exits: list[Exit[object]] = []
        for incoming in self.exits:
            for clean in cleanup_exits:
                guard = _and_guards(incoming.guard, clean.guard)
                if isinstance(clean, Halted):
                    exits.append(Halted(guard, clean.effect, clean.state))
                    continue
                if restores(clean.value):
                    if isinstance(incoming, Completed):
                        exits.append(Completed(guard, incoming.value))
                    else:
                        exits.append(Halted(guard, incoming.effect, incoming.state))
                else:
                    # Terminal cleanup completion supersedes (return in finally).
                    exits.append(Completed(guard, clean.value))
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
            RetainedObligation,
            exit_disposition_effect,
        )

        exit_exits = exit_es.exits
        exits: list[Exit[object]] = []
        for incoming in self.exits:
            for ex in exit_exits:
                guard = _and_guards(incoming.guard, ex.guard)
                if isinstance(ex, Halted):
                    exits.append(Halted(guard, ex.effect, ex.state))
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
                    obligation = verdict.obligation
                    for sub_guard, sub_verdict in (
                        (_and_guards(guard, obligation), verdict.held),
                        (
                            _and_guards(guard, complement_guard(obligation)),
                            verdict.failed,
                        ),
                    ):
                        if sub_verdict is None:
                            exits.append(Completed(sub_guard, carried))
                        else:
                            exits.append(Halted(sub_guard, sub_verdict, carried))
                    continue
                if verdict is None:
                    exits.append(Completed(guard, carried))
                else:
                    exits.append(Halted(guard, verdict, carried))
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
                if isinstance(ex, Halted):
                    exits.append(Halted(guard, ex.effect, ex.state))
                    continue
                if isinstance(incoming, Completed):
                    exits.append(Completed(guard, incoming.value))
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
                exits.append(Completed(_and_guards(guard, truth), incoming.state))
                exits.append(
                    Halted(
                        _and_guards(guard, falsity),
                        incoming.effect,
                        incoming.state,
                    )
                )
        return ExitSet(tuple(exits)).normalize()

    def collapse(self):
        """Return the old linear Outcome only for one unconditional exit."""
        normalized = self.normalize()
        if len(normalized.exits) != 1 or not _is_true(normalized.exits[0].guard):
            return self if normalized == self else normalized
        exit_ = normalized.exits[0]
        if isinstance(exit_, Completed):
            return Complete(exit_.value)
        return Incomplete(exit_.effect)


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
    return Complete(completed[0].value)


def outcome_to_exitset(outcome) -> ExitSet:
    if isinstance(outcome, ExitSet):
        return outcome
    if isinstance(outcome, Complete):
        return ExitSet.completed(outcome.value)
    if isinstance(outcome, Incomplete):
        if outcome.branch_conditions:
            return ExitSet.halted(outcome.effect, and_(list(outcome.branch_conditions)))
        return ExitSet.halted(outcome.effect)
    raise TypeError(type(outcome))


__all__ = [
    "Completed",
    "ExitSet",
    "Halted",
    "complement_guard",
    "false_guard",
    "sole_completed_outcome",
    "true_guard",
    "outcome_to_exitset",
]
