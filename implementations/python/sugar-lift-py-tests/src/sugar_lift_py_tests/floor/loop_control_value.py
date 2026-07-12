from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class LoopControlValue(FloorValue):
    action: str
    locus: str

    def follow_rest(self, rest, reduce):
        del reduce
        return rest

    def guarded(self, formula):
        from .guarded_loop_control import GuardedLoopControl

        return GuardedLoopControl((formula,), self.action, self.locus)

    def post_contribution(self):
        return (_loop_control_formula(self.action, self.locus),)


def _loop_control_formula(action: str, locus: str, guards: tuple = ()):
    from sugar_lift_py_tests.ir import and_, ctor, eq, implies, make_var, str_const

    spelling = "py.loop_exit" if action == "break" else "py.loop_skip"
    formula = eq(
        make_var(f"loop-control:{locus}"),
        ctor(spelling, [str_const(locus)]),
    )
    if guards:
        guard = guards[0] if len(guards) == 1 else and_(list(guards))
        formula = implies(guard, formula)
    from sugar_lift_py_tests.proofir.scope import ScopedLoopControlWitness

    return ScopedLoopControlWitness(action=action, locus=locus).close(formula)
