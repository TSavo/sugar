from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import RaiseEffect

from .exception_value import ExceptionValue
from .exception_cause_value import ExceptionCauseValue
from .floor_value import FloorValue


@dataclass(frozen=True)
class RaiseValue(FloorValue):
    """A Python raise exit carried by a block frontier.

    This is control-flow data, not an `Incomplete`: a `TrySugar` may route it through
    a matching handler before universe lowering decides what residual effects remain.
    """

    effect: RaiseEffect
    scope: object = None
    exception: ExceptionValue | None = None
    cause: ExceptionCauseValue | None = None

    def follow_rest(self):
        # Code after an unguarded raise never runs and is not part of the
        # block record (unreachable). Drop it — same posture as a hard exit.
        from sugar_lift_py_tests.outcome.follow_step import FollowStep

        return FollowStep.halt(keeps_rest=False)

    def truth(self, site):
        # A raise is not a Python boolean. Expression evaluation already halted
        # with the exceptional exit; demanding truthiness of the raise terminal
        # is a force-floor stage bug (owner=truth, observed=RaiseValue). Re-emit
        # the effect so `if <expr-that-raises>:` propagates rather than panics.
        del site
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(self.effect)

    def guarded(self, formula):
        from sugar_lift_py_tests.floor.guarded_raise import GuardedRaise

        return GuardedRaise(
            guards=(formula,),
            effect=self.effect,
            scope=self.scope,
            cause=self.cause,
        )

    def post_contribution(self):
        return (_exceptional_exit_formula(self.effect),)


def _exceptional_exit_formula(effect: RaiseEffect, guards: tuple = ()):
    # Bare ``raise`` (re-raise of the active exception) is a source-cited
    # exceptional exit: the coordinate is ``reraise``, not a silent drop and
    # not a fabricated exception class. Explicit ``raise Exc(...)`` keeps its
    # constructed name. Absence of both would be a construction gap elsewhere.
    exception_name = (
        effect.exception_name
        if effect.exception_name is not None
        else (None if effect.exception_type_coordinate is not None else "reraise")
    )

    from sugar_lift_py_tests.ir import and_, eq, implies, make_var

    exit_formula = eq(
        make_var("out"),
        _exceptional_exit_term(effect, exception_name=exception_name),
    )
    if not guards:
        return exit_formula
    guard = guards[0] if len(guards) == 1 else and_(list(guards))
    return implies(guard, exit_formula)


def _exceptional_exit_term(effect: RaiseEffect, *, exception_name: str | None = None):
    """Project the one source-cited term shared by raise posts and selections."""
    from sugar_lift_py_tests.ir import ctor, str_const

    if effect.exception_type_coordinate is not None and exception_name is None:
        name_term = effect.exception_type_coordinate
    else:
        name = (
            exception_name
            if exception_name is not None
            else effect.exception_name or "reraise"
        )
        name_term = str_const(name)
    return ctor(
        "py.exceptional_exit",
        [
            name_term,
            str_const(
                f"{effect.blame or '<unknown raise locus>'}"
                f"#source-sha256={effect.source_sha256 or 'unavailable'}"
            ),
        ],
    )
