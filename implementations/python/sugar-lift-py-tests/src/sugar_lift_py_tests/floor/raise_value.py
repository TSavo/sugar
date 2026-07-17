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
        effect.exception_name if effect.exception_name is not None else "reraise"
    )

    from sugar_lift_py_tests.ir import and_, ctor, eq, implies, make_var, str_const

    exit_formula = eq(
        make_var("out"),
        ctor(
            "py.exceptional_exit",
            [
                str_const(exception_name),
                str_const(
                    f"{effect.blame or '<unknown raise locus>'}"
                    f"#source-sha256={effect.source_sha256 or 'unavailable'}"
                ),
            ],
        ),
    )
    if not guards:
        return exit_formula
    guard = guards[0] if len(guards) == 1 else and_(list(guards))
    return implies(guard, exit_formula)
