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

    def contribution(self):
        # Self rides so extend_scope can rebind as-name into enclosing rest.
        # Body entries still splice. inv_contribution does not walk self.
        return (self, *self.body_entries)

    def inv_contribution(self):
        return (
            *self.raises_inv.inv_contribution(),
            *(
                formula
                for entry in self.body_entries
                for formula in entry.inv_contribution()
            ),
        )

    def post_contribution(self):
        return tuple(
            formula
            for entry in self.body_entries
            for formula in entry.post_contribution()
        )

    def edge_contribution(self, source_contract):
        return tuple(
            edge
            for entry in self.body_entries
            for edge in entry.edge_contribution(source_contract)
        )

    def extend_scope(self, ctx):
        if self.as_name is not None and self.as_value is not None:
            return replace(
                ctx,
                temporal=ctx.temporal.bind_value(self.as_name, self.as_value),
            )
        return ctx
