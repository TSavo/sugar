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
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            PredicateValue(py_truthy(self.to_term(owner=str(site))), site)
        )


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


@dataclass(frozen=True)
class BranchResultDecision(FloorValue):
    """A reducer's decision of one branch-result slot on the path it rides:
    the code after it reads the slot as ``decided`` (``BranchResultRefSugar``,
    ``read_binding``), so a phi over the slot takes exactly one arm.

    A live loop decides each name's write slot (``loop_write_slot``) on the
    exit it publishes on (``LoopRecurrenceSugar._post_loop_writes``).  Like
    a ground ``if`` (``IfSugar._ground_branch_result``) it decides the slot
    in the reduction context and contributes nothing to the record.  The
    decision is this path's own: the context after it gets a new table, so
    no other path sees it.  Under a guard it decides nothing (``guards``),
    as a guarded rebind binds nothing (``GuardedScopeRebind``)."""

    slot: BranchResultSlot
    decided: bool
    site: object = field(default=None, compare=False)
    guards: tuple = ()

    def contribution(self):
        return ()

    def extend_scope(self, ctx):
        if self.guards:
            return ctx
        from dataclasses import is_dataclass, replace

        from sugar_lift_py_tests.floor.scope_rebind import _context_for_rebind

        ctx = _context_for_rebind(ctx, owner="BranchResultDecision")
        table = getattr(ctx, "ground_branch_results", None)
        if not isinstance(table, dict) or not is_dataclass(ctx):
            return ctx
        if self.decided:
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            literal = TrueBoolLiteralSugar(site=self.site)
        else:
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )

            literal = FalseBoolLiteralSugar(site=self.site)
        return replace(
            ctx, ground_branch_results={**table, self.slot.slot_id: literal}
        )

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:branch_result_decision",
            [
                str_const(self.slot.slot_id),
                str_const("true" if self.decided else "false"),
            ],
        )

    def guarded(self, formula):
        from dataclasses import replace

        return replace(self, guards=(formula, *self.guards))


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
