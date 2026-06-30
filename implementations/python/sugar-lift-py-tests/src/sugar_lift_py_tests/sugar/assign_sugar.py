from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BoundVar
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AssignSugar(Sugar, role=SugarRole.STATEMENT):
    """A `name = <rhs>` statement. Its child is the RHS expression -- built by the
    factory at the TERM role and handed in. Desugaring does NOT reduce the rhs; it
    yields a BoundVar that ALIASES the name to the rhs SOURCE. The block threads it as
    a let, a reference recomposes it, and a later pass can recover the original
    expression (`let x = y()` keeps `y()`)."""

    name: str
    value: SugarBody

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Assign" and site.assign_target_name() is not None

    @classmethod
    def build(cls, site, ctx) -> "AssignSugar":
        name = site.assign_target_name()
        if name is None:
            raise TypeError("AssignSugar claim built a non-single-name assignment")
        return cls(
            name=name,
            value=ctx.build_body(site.assign_value(), SugarRole.TERM),
        )

    def desugar(self, ctx) -> Outcome:
        # The rhs is NOT reduced here -- it is bound LAZILY as a BoundVar that aliases the
        # name to the rhs SOURCE (recoverable: `b = x` keeps `x`). An effect in the rhs
        # (`x = 1/0`) surfaces when the binding is USED (the reference reduces the source
        # to Incomplete and bubbles). Captured against the DEFINITION scope so a self-
        # referential rebind reads the old value.
        return Complete(BoundVar(self.name, self.value, scope=ctx))
