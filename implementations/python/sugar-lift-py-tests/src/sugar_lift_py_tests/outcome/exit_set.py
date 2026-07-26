"""Guarded block exits: the effect-dimension phi for statement sequencing."""

from __future__ import annotations

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


class ExitSetFactoringGap(ValueError):
    """A completed face that a guarded-value chain cannot faithfully carry.

    Loud on contact, in the same shape as ``SourceCallBindingGap``: the message
    names the two guards, why the collapse would lose an outcome, and the fix.
    """


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


def _destination_key(exit_: "Exit[T]") -> object:
    """Bucket key for an exit's DESTINATION, ignoring its guard.

    Two exits merge exactly when their destinations are equal, so the guard —
    the thing the merge rewrites — must not enter the key. Returns
    ``_UNHASHABLE`` when the destination cannot be hashed.
    """
    try:
        if isinstance(exit_, Completed):
            return ("completed", hash(exit_.value))
        return ("halted", hash(exit_.effect), hash(exit_.state))
    except TypeError:
        return _UNHASHABLE


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

        for index, arm in enumerate(completed):
            for other in completed[index + 1 :]:
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
                        "  fix: give the producing sugar complementary guards "
                        "(the branch join shape ``g`` / ``not g``), or extend "
                        "_are_exclusive to see the exclusion these two guards "
                        "already carry. Do NOT re-materialize the product: that "
                        "is the m ** k blow-up #6309 removed."
                    )

        from sugar_lift_py_tests.floor import GuardedValue

        chain = completed[-1].value
        for arm in reversed(completed[:-1]):
            chain = GuardedValue(arm.guard, arm.value, chain)

        face_guard = completed[0].guard
        for arm in completed[1:]:
            face_guard = _or_guards(face_guard, arm.guard)

        factored = Completed(face_guard, chain)
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
    "ExitSetFactoringGap",
    "Halted",
    "complement_guard",
    "false_guard",
    "sole_completed_outcome",
    "true_guard",
    "outcome_to_exitset",
]
