from __future__ import annotations

from dataclasses import dataclass, replace

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class FunctionDefSugar(Sugar, role=SugarRole.STATEMENT):
    """`def name(params): body`. The body becomes a universe: each parameter
    binds a SymbolicValue (the universe variable whose sort is the compiler's
    to decide), the body reduces to its record under that scope, and the
    result is a UniverseValue -- name, formals, record. The slots are
    projections of the record. Plain positional parameters only; defaults,
    keyword-only, *args/**kwargs, and decorators stay loud gaps."""

    name: str
    formals: tuple[str, ...]
    body: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "FunctionDef":
            return False
        min_args, max_args = site.function_positional_arity()
        return min_args == max_args and not site.function_decorators()

    @classmethod
    def new(cls, site, ctx) -> "FunctionDefSugar":
        # The body is factory-built as ONE Block (audited), never reduced here.
        return cls(
            name=site.function_name(),
            formals=tuple(site.function_params()),
            body=ctx.build_body(site.function_body_block(), SugarRole.STATEMENT),
            blame=site.blame,
        )

    @classmethod
    def witnesses(cls):
        # The def IS the vehicle of every witness; its own pair rides the
        # simplest universe: out == z, discriminated at the callsite.
        prefix = "def A(z):\n    return z\n\n"
        return _call_pair(
            name="function_def_return",
            owner_sugar="FunctionDefSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Bind each parameter to its universe variable, reduce the body under
        # that scope, and the result is the universe.
        from sugar_lift_py_tests.floor import SymbolicValue, UniverseValue
        from sugar_lift_py_tests.ir import make_var

        temporal = ctx.temporal
        for formal in self.formals:
            temporal = temporal.bind_value(formal, SymbolicValue(make_var(formal)))
        scoped = replace(ctx, temporal=temporal)
        return self.body.reduce(scoped).and_then(
            lambda record: Complete(
                UniverseValue(name=self.name, formals=self.formals, record=record)
            )
        )
