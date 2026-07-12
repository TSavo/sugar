from __future__ import annotations

from dataclasses import dataclass, replace

from .floor_value import FloorValue


@dataclass(frozen=True)
class CurriedLoopBody:
    body: object
    carried: tuple[str, ...]

    def desugar(self, ctx):
        from sugar_lift_py_tests.floor import TupleValue
        from sugar_lift_py_tests.outcome import Complete

        _record, final_ctx = self.body.sugar.reduce_with_scope(ctx)
        values = tuple(final_ctx.temporal.value_for(name) for name in self.carried)
        return Complete(values[0] if len(values) == 1 else TupleValue(values))


@dataclass(frozen=True)
class CurriedLoopScope(FloorValue):
    callsite: object
    carried: tuple[str, ...]

    def extend_scope(self, ctx):
        temporal = ctx.temporal
        if not self.carried:
            return ctx
        if len(self.carried) == 1:
            temporal = temporal.bind_value(self.carried[0], self.callsite)
        else:
            from sugar_lift_py_tests.floor import TermValue

            for index, name in enumerate(self.carried):
                projection = self.callsite.subscript(TermValue(index), self.callsite.site)
                temporal = temporal.bind_value(name, projection.value)
        return replace(ctx, temporal=temporal)

    def contribution(self):
        return ()
