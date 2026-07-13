from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class LambdaSugar(Sugar, role=SugarRole.TERM):
    """`lambda <params>: <body>` -- in-source anonymous function value.

    Carries simple-Name formals and the body expression SugarBody (present for
    dig, unlike CallSugar's body=None for opaque vendor calls). Desugar binds
    each formal to a parameter coordinate (SymbolicValue of make_var), reduces
    the body under that scope (so free params stand), then builds a
    LambdaCallable carrying the params and the in-source body.

    OWNED: observed == "Lambda" with plain positional names only (zero or more).
    LOUD gaps: defaults, pos-only, kw-only, *args, **kwargs -- never silently
    drop a parameter shape. FunctionDef is a different observed kind.
    """

    formals: tuple[str, ...]
    body: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Lambda":
            return False
        return site.lambda_is_simple_positional()

    @classmethod
    def new(cls, site, ctx) -> "LambdaSugar":
        # Param names + body expression (TERM). Never reduce here.
        return cls(
            formals=tuple(site.lambda_params()),
            body=ctx.build_body(site.lambda_body(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Lambda value rides in the body; pair discriminates on return face.
        prefix = "def A(z):\n" "    f = lambda x: x\n" "    return 1\n" "\n"
        return _call_pair(
            name="lambda_return",
            owner_sugar="LambdaSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Bind formals to universe variables, reduce body under that scope,
        # then the lambda value carries params + the in-source body SugarBody.
        from sugar_lift_py_tests.floor import LambdaCallable, SymbolicValue
        from sugar_lift_py_tests.ir import make_var

        temporal = ctx.temporal
        for formal in self.formals:
            temporal = temporal.bind_value(formal, SymbolicValue(make_var(formal)))
        scoped = replace(ctx, temporal=temporal)
        return self.body.reduce(scoped).and_then(
            lambda _reduced: Complete(
                LambdaCallable(parameters=self.formals, body=self.body)
            )
        )

    def walk_children(self):
        return (self.body,)
