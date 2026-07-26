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
        """Drop false exits and merge equal destinations by disjoining guards."""
        merged: list[Exit[T]] = []
        for exit_ in self.exits:
            if _is_false(exit_.guard):
                continue
            for index, prior in enumerate(merged):
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
                merged.append(exit_)
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
