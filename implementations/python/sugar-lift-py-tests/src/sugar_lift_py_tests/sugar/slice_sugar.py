"""A slice `lower:upper:step` (as it appears in `xs[1:2]`, `xs[::2]`, ...).

A slice is a value: `slice(lower, upper, step)`. It reduces each present bound
and stands as the `py.slice` coordinate over their terms; an omitted bound is
`None` (its NoneValue term), exactly as Python fills it. The container's
subscript floor consumes this coordinate -- this only constructs it.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class SliceSugar(Sugar):
    lower: object  # sugar or None (omitted bound)
    upper: object
    step: object
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Incomplete

        terms = []
        for bound in (self.lower, self.upper, self.step):
            if bound is None:
                terms.append(NoneValue().to_term(owner="slice"))
                continue
            out = bound.desugar(ctx)
            if isinstance(out, Incomplete):
                return out
            terms.append(out.value.to_term(owner="slice"))
        return Complete(SymbolicValue(ctor("py.slice", terms)))
