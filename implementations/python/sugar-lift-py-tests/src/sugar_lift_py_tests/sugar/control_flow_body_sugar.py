from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula, and_, eq, implies, make_var


@dataclass(frozen=True)
class ControlFlowBodySugar:
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
    collapses to a plain equality (straight-line bodies are the degenerate case).
    """

    parameter: str
    # each path: (tuple of guard Formulas, the return-value Term)
    paths: tuple[tuple[tuple[Formula, ...], object], ...]
    formals: tuple[str, ...]
    statement_count: int

    def apply(self, argument):  # pragma: no cover - lowers to ProofIR
        del argument
        raise TypeError("ControlFlowBodySugar lowers to ProofIR; call constraint_formulas")

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

    def factory_steps(self, function) -> list[tuple[str, str, object, str]]:
        return [
            ("ControlFlowBodySugar", "Branch", stmt, "Formula") for stmt in function.body
        ]

    def constraint_formula_steps(self) -> list[Formula | None]:
        # the whole branched universe is emitted once, on the final statement
        return [None] * (self.statement_count - 1) + [self.constraint_formulas()[0]]
