from __future__ import annotations

from dataclasses import dataclass, replace

from .bound_var import BoundVar


@dataclass(frozen=True)
class ModuleBoundVar(BoundVar):
    """A source alias whose declared store belongs to the module frame."""

    def extend_scope(self, ctx):
        if ctx.module_temporal is None:
            from sugar_lift_py_tests.factory import factory_panic_gap

            factory_panic_gap(
                owner=type(self).__name__,
                blame=self.name,
                observed="dynamic module frame",
                requested="statically known module temporal",
                fix="construct the function through the module audit door",
            )
        module_temporal = ctx.module_temporal.bind_value(self.name, self)
        return replace(
            ctx,
            temporal=ctx.temporal.bind_value(self.name, self),
            module_temporal=module_temporal,
        )
