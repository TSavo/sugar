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
    def halted(cls, effect: Effect, guard: Formula | None = None) -> "ExitSet[T]":
        return cls((Halted(guard or true_guard(), effect),)).normalize()

    @classmethod
    def conditional_halt(
        cls, guard: Formula, effect: Effect, state: T
    ) -> "ExitSet[T]":
        return cls((Halted(guard, effect), Completed(not_(guard), state))).normalize()

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
                exits.append(Halted(combined, exit_.effect))
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
                )
                if same_completed:
                    merged[index] = Completed(
                        _or_guards(prior.guard, exit_.guard), prior.value
                    )
                    break
                if same_halted:
                    merged[index] = Halted(
                        _or_guards(prior.guard, exit_.guard), prior.effect
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
                    exits.append(Halted(guard, following.effect))
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
                    exits.append(Halted(guard, clean.effect))
                    continue
                if restores(clean.value):
                    if isinstance(incoming, Completed):
                        exits.append(Completed(guard, incoming.value))
                    else:
                        exits.append(Halted(guard, incoming.effect))
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
        """Run constructed ``__exit__`` over every body exit (resource ``with``).

        ``exit_es`` is the already-reduced exit ExitSet (built once from tree
        sugar, not a callback). ``disposition`` is a **typed** exit contract:

        - ``NeverSuppresses`` — restore body halt (exit still ran; may supersede)
        - ``ExitSuppressionContract`` — proven named suppress / restore
        - ``RuntimeSelected`` — open residual under the guard (never guessed)
        - ``Suppresses(matcher)`` — membrane matcher authority only

        Laws:

        - Exit **halt** supersedes the incoming exit.
        - Exit **completion** on a **Completed** incoming keeps the body value.
        - Exit **completion** on a **Halted** incoming applies ``disposition``:
          suppress → consume; restore → rethrow; open → residual halt.
        """
        from sugar_lift_py_tests.outcome.resource_exit_disposition import (
            disposition_verdict,
        )

        exit_exits = exit_es.exits
        exits: list[Exit[object]] = []
        for incoming in self.exits:
            for ex in exit_exits:
                guard = _and_guards(incoming.guard, ex.guard)
                if isinstance(ex, Halted):
                    exits.append(Halted(guard, ex.effect))
                    continue
                if isinstance(incoming, Completed):
                    exits.append(Completed(guard, incoming.value))
                    continue
                # Incoming Halted + exit completed → typed disposition.
                verdict = disposition_verdict(disposition, incoming.effect)
                if verdict == "suppress":
                    exits.append(Completed(guard, None))
                elif verdict == "open":
                    exits.append(Halted(guard, incoming.effect))
                else:
                    # restore
                    exits.append(Halted(guard, incoming.effect))
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


def outcome_to_exitset(outcome) -> ExitSet:
    if isinstance(outcome, ExitSet):
        return outcome
    if isinstance(outcome, Complete):
        return ExitSet.completed(outcome.value)
    if isinstance(outcome, Incomplete):
        if outcome.branch_conditions:
            return ExitSet.halted(
                outcome.effect, and_(list(outcome.branch_conditions))
            )
        return ExitSet.halted(outcome.effect)
    raise TypeError(type(outcome))


__all__ = [
    "Completed",
    "ExitSet",
    "Halted",
    "false_guard",
    "true_guard",
    "outcome_to_exitset",
]
