from __future__ import annotations

from dataclasses import dataclass, field

from .floor_value import FloorValue


def returned_term(value, held, site):
    """The term a post states ``out`` equal to: ``held``, the value as the
    returning frame holds it at its ``return`` (``site``), named by
    ``object_identity.identity_term`` -- its contents where they are the
    object's at the return, its identity where they are not (a module
    global, an object a call may have changed).  ``value`` is the same value
    as the caller holds it (``arrived``), whose contents are never current
    there; it is projected only where no held value was recorded."""
    if held is None:
        return value.to_term(owner="post")
    from .object_identity import identity_term

    return identity_term(held, site, "returned", owner="post")


@dataclass(frozen=True)
class ReturnValue(FloorValue):
    """The outcome of a `return` statement: the value the path returns. A block
    carries it; when a body becomes a universe, a ReturnValue under its guards
    becomes `out == value`.  ``value`` is what the caller holds
    (``object_identity.arrived``); ``held`` and ``site`` are the value as
    the returning frame holds it and the ``return``'s site, what the post
    states (``returned_term``)."""

    value: object
    held: object = field(default=None, compare=False)
    site: object = field(default=None, compare=False)

    def post_contribution(self):
        # The exit the post slot binds: out == <this term>. This is the LIFT's
        # own sentence asserting true equality of out with the exit term --
        # reflexive-safe, so ir.eq (SMT =), not py.eq (vendor Python ==).
        from sugar_lift_py_tests.ir import eq, make_var

        out = make_var("out")
        conditional_post = getattr(self.value, "post_formula", None)
        if callable(conditional_post):
            return (conditional_post(out),)
        return (eq(out, returned_term(self.value, self.held, self.site)),)

    def follow_rest(self):
        # Code after an unguarded return never runs: keep it raw, unreduced.
        from sugar_lift_py_tests.outcome.follow_step import FollowStep

        return FollowStep.halt(keeps_rest=True)

    def guarded(self, formula):
        # A return under a guard is a GuardedReturn.
        from sugar_lift_py_tests.floor.guarded_return import GuardedReturn

        return GuardedReturn(
            guards=(formula,), value=self.value, held=self.held, site=self.site
        )

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
