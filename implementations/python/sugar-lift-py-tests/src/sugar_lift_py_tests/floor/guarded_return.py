from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class GuardedReturn(FloorValue):
    """A return reached only under a guard -- a branch's return. `guards` is the
    conjunction of `if` conditions on the way to it (an else branch negates its
    test). When a body becomes a universe, a GuardedReturn lowers to
    `implies(and(guards), out == value)`. An unguarded return is a ReturnValue."""

    guards: tuple
    value: object

    def post_contribution(self):
        # The guarded exit: implies(and(guards), out == value). out == value is
        # the LIFT's own sentence (reflexive-safe), so ir.eq -- not py.eq.
        from sugar_lift_py_tests.ir import and_, eq, implies, make_var

        guard = self.guards[0] if len(self.guards) == 1 else and_(list(self.guards))
        out = make_var("out")
        conditional_post = getattr(self.value, "post_formula", None)
        post = (
            conditional_post(out)
            if callable(conditional_post)
            else eq(out, self.value.to_term(owner="post"))
        )
        return (implies(guard, post),)

    def guarded(self, formula):
        # A nested guard stacks: the outer condition joins the conjunction.
        return GuardedReturn(guards=(formula, *self.guards), value=self.value)

    def edge_contribution(self, source_contract):
        return self.value.edge_contribution(source_contract)

    def derived_post_contribution(self):
        from sugar_lift_py_tests.floor.return_value import ReturnValue
        from sugar_lift_py_tests.ir import and_, implies

        companions = ReturnValue(self.value).derived_post_contribution()
        if not companions:
            return ()
        guard = self.guards[0] if len(self.guards) == 1 else and_(list(self.guards))
        return tuple(implies(guard, formula) for formula in companions)
