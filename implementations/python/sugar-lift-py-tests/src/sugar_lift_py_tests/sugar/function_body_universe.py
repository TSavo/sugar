from __future__ import annotations

from abc import ABC, abstractmethod

from sugar_lift_py_tests.ir import Formula
from sugar_lift_py_tests.sugar_body import SugarBody


class FunctionBodyUniverse(ABC):
    """A multi-statement function body, composed as ONE Block and lowered to a universe.

    Subclasses define ONLY the universe formula (`constraint_formulas`): guarded
    implications for control flow, `str.eq-bv-blocks` for a string encoder. Everything
    else is shared and DERIVED from `statements` -- the Block's composed lines, each a
    SugarBody carrying the FactoryAuditRow the factory minted when it built that line:
      * the factory walk is one row per source statement, in build order, read off each
        line's audit row (the sugar that owns it, its AST kind), and
      * the universe is emitted on the last line (the return); the rest -- inert lets, a
        docstring -- are support.

    Nothing is flattened on the way in: the composed objects are carried, the walk is
    read back out of them.
    """

    # the Block's composed lines, in build order (concrete subclasses hold the field).
    statements: tuple[SugarBody, ...]

    @abstractmethod
    def constraint_formulas(self) -> list[Formula]:
        """The body's universe formula(s)."""

    def factory_steps(self, function) -> list[tuple[str, str, object, str]]:
        return [
            (
                line.audit_row.selected,
                line.audit_row.observed,
                function.body[index],
                "—",
            )
            for index, line in enumerate(self.statements)
        ]

    def constraint_formula_steps(self) -> list[Formula | None]:
        count = len(self.statements)
        return [None] * (count - 1) + [self.constraint_formulas()[0]]

    def apply(self, argument):  # pragma: no cover - lowers to ProofIR
        del argument
        raise TypeError(
            f"{type(self).__name__} lowers to ProofIR; call constraint_formulas"
        )
