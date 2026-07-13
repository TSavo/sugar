from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class ReturnValue(FloorValue):
    """The outcome of a `return` statement: the value the path returns. A block
    carries it; when a body becomes a universe, a ReturnValue under its guards
    becomes `out == value`."""

    value: object

    def post_contribution(self):
        # The exit the post slot binds: out == <this term>. This is the LIFT's
        # own sentence asserting true equality of out with the exit term --
        # reflexive-safe, so ir.eq (SMT =), not py.eq (vendor Python ==).
        from sugar_lift_py_tests.ir import eq, make_var

        out = make_var("out")
        conditional_post = getattr(self.value, "post_formula", None)
        if callable(conditional_post):
            return (conditional_post(out),)
        return (eq(out, self.value.to_term(owner="post")),)

    def follow_rest(self, rest, reduce):
        # Code after an unguarded return never runs: keep it raw, unreduced.
        del reduce
        return rest

    def guarded(self, formula):
        # A return under a guard is a GuardedReturn.
        from sugar_lift_py_tests.floor.guarded_return import GuardedReturn

        return GuardedReturn(guards=(formula,), value=self.value)

    def project_callsite_with(self, operation, ctx):
        return operation.project_return(self, ctx)

    def edge_contribution(self, source_contract):
        return self.value.edge_contribution(source_contract)

    def derived_post_contribution(self):
        companion = getattr(self.value, "companion_formula", None)
        if not callable(companion):
            return ()
        formula = companion(owner="ReturnValue.companion")
        if formula is None:
            return ()
        from sugar_lift_py_tests.ir import eq, make_var

        return (
            formula,
            eq(
                make_var("out"),
                self.value.computed.to_term(owner="ReturnValue.computed"),
            ),
        )
