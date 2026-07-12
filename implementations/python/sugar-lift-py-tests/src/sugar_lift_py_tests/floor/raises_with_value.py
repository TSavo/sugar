from __future__ import annotations

from dataclasses import dataclass, replace

from .floor_value import FloorValue
from .inv_value import InvValue


@dataclass(frozen=True)
class RaisesWithValue(FloorValue):
    """Outcome of with pytest.raises(T) as exc_info: body.

    Carries the stated pytest.raises inv, body record entries, and threads
    the optional as-binding into the rest of the enclosing block (asserts
    after the with need exc_info bound — including after an outer
    freeze_time with that wraps the raises).

    Contribution includes self (not only flattened inv) so BlockValue /
    outer with splicing still has an entry that implements extend_scope.
    """

    raises_inv: InvValue
    body_entries: tuple
    as_name: str | None = None
    as_value: FloorValue | None = None
    guards: tuple = ()

    def contribution(self):
        # Self rides so extend_scope can rebind as-name into enclosing rest.
        # Body entries still splice. inv_contribution does not walk self.
        return (self, *self.body_entries)

    def inv_contribution(self):
        formulas = (
            *self.raises_inv.inv_contribution(),
            *(
                formula
                for entry in self.body_entries
                for formula in entry.inv_contribution()
            ),
        )
        return self._guard_formulas(formulas)

    def post_contribution(self):
        formulas = tuple(
            formula
            for entry in self.body_entries
            for formula in entry.post_contribution()
        )
        return self._guard_formulas(formulas)

    def _guard_formulas(self, formulas):
        if not self.guards:
            return formulas
        from sugar_lift_py_tests.ir import and_, implies

        guard = self.guards[0] if len(self.guards) == 1 else and_(list(self.guards))
        return tuple(implies(guard, formula) for formula in formulas)

    def guarded(self, formula):
        return replace(self, guards=(formula, *self.guards))

    def mint_contribution(self, name, formals):  # type: ignore[override]
        return (
            *self.raises_inv.mint_contribution(name, formals),
            *(
                row
                for entry in self.body_entries
                for row in entry.mint_contribution(name, formals)
            ),
        )

    def edge_contribution(self, source_contract):
        return tuple(
            edge
            for entry in self.body_entries
            for edge in entry.edge_contribution(source_contract)
        )

    def extend_scope(self, ctx):
        if self.guards:
            return ctx
        if self.as_name is not None and self.as_value is not None:
            return replace(
                ctx,
                temporal=ctx.temporal.bind_value(self.as_name, self.as_value),
            )
        return ctx
