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

    OWNED: observed == "Lambda" with positional names, evaluated defaults,
    keyword-only names, and optional ``*args`` / ``**kwargs`` collectors.
    Positional-only parameters remain loud until their binding arm exists.
    FunctionDef is a different observed kind.
    """

    formals: tuple[str, ...]
    defaults: tuple[SugarBody, ...]
    kwonly_formals: tuple[str, ...]
    kwonly_defaults: tuple[SugarBody | None, ...]
    vararg_formal: str | None
    kwarg_formal: str | None
    body: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Lambda":
            return False
        return site.lambda_has_constructible_signature()

    @classmethod
    def new(cls, site, ctx) -> "LambdaSugar":
        # Param names + body expression (TERM). Never reduce here.
        return cls(
            formals=tuple(site.lambda_params()),
            defaults=tuple(
                ctx.build_body(default, SugarRole.TERM)
                for default in site.lambda_defaults()
            ),
            kwonly_formals=site.lambda_kwonly_params(),
            kwonly_defaults=tuple(
                None if default is None else ctx.build_body(default, SugarRole.TERM)
                for default in site.lambda_kwonly_defaults()
            ),
            vararg_formal=site.lambda_vararg_param(),
            kwarg_formal=site.lambda_kwarg_param(),
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
        return self._reduce_defaults(self.defaults, (), ctx)

    def _reduce_defaults(self, remaining, reduced, ctx) -> Outcome:
        if not remaining:
            return self._reduce_kwonly_defaults(
                self.kwonly_defaults,
                (),
                reduced,
                ctx,
            )
        head, *tail = remaining
        return head.reduce(ctx).and_then(
            lambda value: self._reduce_defaults(tuple(tail), (*reduced, value), ctx)
        )

    def _reduce_kwonly_defaults(
        self, remaining, reduced, positional_defaults, ctx
    ) -> Outcome:
        if not remaining:
            return self._finish(positional_defaults, reduced, ctx)
        head, *tail = remaining
        if head is None:
            return self._reduce_kwonly_defaults(
                tuple(tail), (*reduced, None), positional_defaults, ctx
            )
        return head.reduce(ctx).and_then(
            lambda value: self._reduce_kwonly_defaults(
                tuple(tail), (*reduced, value), positional_defaults, ctx
            )
        )

    def _finish(self, default_values, kwonly_default_values, ctx) -> Outcome:
        # Bind formals to universe variables, reduce body under that scope,
        # then the lambda value carries params + the in-source body SugarBody.
        from sugar_lift_py_tests.floor import LambdaCallable, SymbolicValue
        from sugar_lift_py_tests.ir import make_var

        temporal = ctx.temporal
        for formal in (
            *self.formals,
            *self.kwonly_formals,
            *(() if self.vararg_formal is None else (self.vararg_formal,)),
            *(() if self.kwarg_formal is None else (self.kwarg_formal,)),
        ):
            temporal = temporal.bind_value(formal, SymbolicValue(make_var(formal)))
        scoped = replace(ctx, temporal=temporal)
        return self.body.reduce(scoped).and_then(
            lambda _reduced: Complete(
                LambdaCallable(
                    parameters=self.formals,
                    body=self.body,
                    default_values=default_values,
                    keyword_only_parameters=self.kwonly_formals,
                    keyword_only_default_values=kwonly_default_values,
                    vararg_parameter=self.vararg_formal,
                    kwarg_parameter=self.kwarg_formal,
                )
            )
        )

    def walk_children(self):
        return (
            *self.defaults,
            *(default for default in self.kwonly_defaults if default is not None),
            self.body,
        )
