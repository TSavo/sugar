from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula, Term, and_, eq, implies, make_var
from sugar_lift_py_tests.sugar.function_body_universe import FunctionBodyUniverse
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ControlFlowBodySugar(FunctionBodyUniverse):
    """A function body with branching returns, lifted as guarded implications.

    Control flow is NOT executed -- it becomes first-order logic. Each return path
    is `(guard, out == return-term)`, where the guard is the conjunction of the
    `if` conditions on the way to that return (the `else` branch negates the test).
    The body's universe is the conjunction of those implications:

        (k == 2)          -> out == ...
        (k != 2 & k == 1) -> out == ...
        (k != 2 & k != 1) -> out == ...

    z3 does the branching for free: given the bound inputs, the guards resolve and
    the active path's `out == ...` is the live constraint. A single unguarded path
    collapses to a plain equality (straight-line bodies are the degenerate case). The
    per-line walk is inherited.
    """

    parameter: str
    # each path: (tuple of guard Formulas, the return-value Term)
    paths: tuple[tuple[tuple[Formula, ...], Term], ...]
    formals: tuple[str, ...]
    statements: tuple[SugarBody, ...] = ()

    def _clauses(self) -> list[Formula]:
        clauses: list[Formula] = []
        for guards, ret_term in self.paths:
            consequent = eq(make_var("out"), ret_term)
            if not guards:
                clauses.append(consequent)
            elif len(guards) == 1:
                clauses.append(implies(guards[0], consequent))
            else:
                clauses.append(implies(and_(list(guards)), consequent))
        return clauses

    def constraint_formulas(self) -> list[Formula]:
        clauses = self._clauses()
        return [clauses[0] if len(clauses) == 1 else and_(clauses)]
