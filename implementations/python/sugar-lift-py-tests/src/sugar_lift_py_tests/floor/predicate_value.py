from __future__ import annotations

from dataclasses import field as dataclass_field, dataclass

from sugar_lift_py_tests.ir import Formula

from .floor_value import FloorValue


@dataclass(frozen=True)
class PredicateValue(FloorValue):
    formula: Formula
    site: object = dataclass_field(default=None, compare=False)
    # CallSiteValues that stood as operands when this formula was emitted --
    # carried so callEdges project from the collapse without a side channel.
    operand_callsites: tuple = dataclass_field(default=(), compare=False)

    def negate(self):
        # A predicate flips by wrapping its formula in not_ -- the formula owns
        # the polarity, the carrier stays PredicateValue; operand callsites ride.
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            PredicateValue(not_(self.formula), self.site, self.operand_callsites)
        )

    def stated(self, site):
        # A symbolic predicate states an inv: the fact the record emits. Operand
        # callsites ride into the InvValue so edges project later.
        from sugar_lift_py_tests.floor.inv_value import InvValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(InvValue(self.formula, site, self.operand_callsites))

    def binary_conditional(self, then, else_body, ctx=None):
        # A symbolic condition cannot pick a face, so it GUARDS: both faces
        # reduce, each entry rides under its polarity. An else with an exiting
        # face is a join ruling that has not happened yet -- loud gap.
        from sugar_lift_py_tests.floor.guarded_faces import GuardedFaces
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import Complete, complete_value

        then_record = complete_value(then.reduce(ctx), owner="guarded-then")
        then_entries = tuple(
            entry.guarded(self.formula) for entry in then_record.contribution()
        )
        then_exits = any(entry.post_contribution() for entry in then_entries)
        else_entries = ()
        if else_body is not None:
            else_record = complete_value(else_body.reduce(ctx), owner="guarded-else")
            else_entries = tuple(
                entry.guarded(not_(self.formula))
                for entry in else_record.contribution()
            )
        return Complete(
            GuardedFaces(
                guard=self.formula,
                entries=(*then_entries, *else_entries),
                then_exits=then_exits and else_body is None,
            )
        )
