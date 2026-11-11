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

    def to_term(self, *, owner: str):
        """The testimony's content: the slot guard and the guard it stands for.

        A factory prefix is content-addressed face by face. This testimony's
        identity is exactly the pair it proves equivalent, so its term carries
        both formulas and nothing else.
        """
        del owner
        from sugar_lift_py_tests.ir import ctor, formula_term

        return ctor(
            "python:branch_result_authentication",
            [
                formula_term(branch_result_guard(self.slot, self.site)),
                formula_term(self.observed_guard),
            ],
        )

    def guarded(self, formula):
        from sugar_lift_py_tests.floor.inv_value import InvValue
        from sugar_lift_py_tests.ir import and_, implies
        from sugar_lift_py_tests.outcome.exit_set import true_guard

        if formula == true_guard():
            # ``true -> A`` is ``A``: an unguarded entry keeps its own
            # authentication form, so consumers that resolve branch-result
            # slots (a native exit's returns) still recognize it.
            return self

        return InvValue(
            implies(formula, and_(list(self.inv_contribution()))), self.site
        )


def resolve_branch_result_guards(formula, authenticated):
    """Replace each branch-result slot literal by its AUTHENTICATED guard.

    A branch guard is spelled ``py.truthy(python:branch_result(<slot>))`` — an
    opaque coordinate. The block also carries a ``BranchResultAuthentication``
    proving that slot equivalent to the real observed comparison. Only that
    testimony may stand in for the slot; an unauthenticated slot returns
    ``None`` and the whole boundary stays loud rather than being read from a
    coordinate nobody proved anything about.
    """
    from sugar_lift_py_tests.ir import _Atomic, _Connective, _ConstStr, _Ctor

    if isinstance(formula, _Connective):
        operands = []
        for operand in formula.operands:
            resolved = resolve_branch_result_guards(operand, authenticated)
            if resolved is None:
                return None
            operands.append(resolved)
        return type(formula)(formula.kind, tuple(operands))
    if not isinstance(formula, _Atomic) or formula.name != "py.truthy":
        return formula
    if len(formula.args) != 1:
        return formula
    term = formula.args[0]
    if not isinstance(term, _Ctor) or term.name != "python:branch_result":
        return formula
    if len(term.args) != 1 or not isinstance(term.args[0], _ConstStr):
        return None
    return authenticated.get(term.args[0].value)
