from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_source_tree.binding_state import BranchResultSlot


@dataclass(frozen=True)
class BranchResultCoordinate(FloorValue):
    slot: BranchResultSlot
    site: object = field(default=None, compare=False)
    symbol_kind: str = field(default="coordinate", init=False)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:branch_result", [str_const(self.slot.slot_id)])

    def truth(self, site):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_truthy
        from sugar_lift_py_tests.outcome import Complete

        return Complete(PredicateValue(py_truthy(self.to_term(owner=str(site))), site))


def branch_result_guard(slot, site):
    from sugar_lift_py_tests.sugar.if_sugar import predicate_formula

    return predicate_formula(BranchResultCoordinate(slot, site), site)


@dataclass(frozen=True)
class BranchResultAuthentication(FloorValue):
    slot: BranchResultSlot
    observed_guard: object
    site: object = field(default=None, compare=False)

    def inv_contribution(self):
        from sugar_lift_py_tests.ir import and_, implies

        slot_guard = branch_result_guard(self.slot, self.site)
        equivalence = and_(
            [
                implies(slot_guard, self.observed_guard),
                implies(self.observed_guard, slot_guard),
            ]
        )
        return (equivalence,)

    def guarded(self, formula):
        from sugar_lift_py_tests.floor.inv_value import InvValue
        from sugar_lift_py_tests.ir import and_, implies

        return InvValue(
            implies(formula, and_(list(self.inv_contribution()))), self.site
        )
