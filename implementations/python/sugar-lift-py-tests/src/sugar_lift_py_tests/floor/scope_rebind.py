from __future__ import annotations

from dataclasses import dataclass, replace

from .floor_value import FloorValue


@dataclass(frozen=True)
class ScopeRebind(FloorValue):
    """A mutation rebinds to the UPDATED VALUE; the history is in the value's nested
    term, not in a recomposable source. Mirror of BoundVar's scope threading -- a let
    that holds the folded result, not a recoverable source body."""

    name: str
    value: FloorValue

    def contribution(self):
        # A rebind is support: present, threaded into scope, contributes nothing to
        # the block record.
        return ()

    def extend_scope(self, ctx):
        # Thread the updated value forward so later statements resolve the name.
        return replace(ctx, temporal=ctx.temporal.bind_value(self.name, self.value))

    def as_expression_statement(self):
        # The rebind IS the statement outcome -- scope rides; contribution is empty.
        from sugar_lift_py_tests.outcome import Complete

        return Complete(self)

    def guarded(self, formula):
        return GuardedScopeRebind((formula,), self.name, self.value)


@dataclass(frozen=True)
class ScopeRebinds(FloorValue):
    """Carry several exact callback mutations back into the caller scope."""

    bindings: tuple[tuple[str, FloorValue], ...]

    def contribution(self):
        return ()

    def extend_scope(self, ctx):
        temporal = ctx.temporal
        for name, value in self.bindings:
            temporal = temporal.bind_value(name, value)
        return replace(ctx, temporal=temporal)

    def as_expression_statement(self):
        from sugar_lift_py_tests.outcome import Complete

        return Complete(self)


@dataclass(frozen=True)
class GuardedScopeRebind(FloorValue):
    """A branch-local rebind carried in the record under one or more guards.

    It deliberately does not extend temporal scope. Definite assignment is owned by
    PredicateValue._joined_bindings, which only joins names present in both faces.
    Keeping this marker non-binding preserves the one-arm NameError path while the
    outer join can still construct a GuardedValue when both faces bind the name.
    """

    guards: tuple
    name: str
    value: FloorValue

    def contribution(self):
        return ()

    def guarded(self, formula):
        return GuardedScopeRebind((formula, *self.guards), self.name, self.value)
