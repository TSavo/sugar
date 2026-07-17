from __future__ import annotations

from dataclasses import field as dataclass_field, dataclass, replace

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class FunctionDefSugar(Sugar, role=SugarRole.DEFINITION):
    """`def name(params): body`. The body becomes a universe: each parameter
    binds a SymbolicValue (the universe variable whose sort is the compiler's
    to decide), the body reduces to its record under that scope, and the
    result is a UniverseValue -- name, formals, record. The slots are
    projections of the record.

    Constructible signatures match LambdaSugar: ordinary positionals (with
    factory-liftable defaults), keyword-only names, and optional ``*args`` /
    ``**kwargs`` collectors all bind as symbolic formals so body asserts mint.
    Positional-only parameters and decorators stay loud gaps. Every default is
    factory-built and reduced, never dropped.
    """

    name: str
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
        if site.observed != "FunctionDef":
            return False
        return (
            site.function_has_constructible_signature()
            and not site.function_decorators()
        )

    @classmethod
    def new(cls, site, ctx) -> "FunctionDefSugar":
        # The body is factory-built as ONE Block (audited), never reduced here.
        formals = list(site.function_params())
        vararg = site.function_vararg_name()
        kwarg = site.function_kwarg_name()
        kwonly = tuple(
            name
            for name, kind in site.function_binding_signature()
            if kind == "keyword-only"
        )
        universe_formals = (
            *formals,
            *kwonly,
            *(() if vararg is None else (vararg,)),
            *(() if kwarg is None else (kwarg,)),
        )
        return cls(
            name=site.function_name(),
            formals=tuple(universe_formals),
            defaults=tuple(
                ctx.build_body(default, SugarRole.TERM)
                for default in site.function_defaults()
            ),
            kwonly_formals=kwonly,
            kwonly_defaults=tuple(
                None if default is None else ctx.build_body(default, SugarRole.TERM)
                for default in site.function_keyword_only_defaults()
            ),
            vararg_formal=vararg,
            kwarg_formal=kwarg,
            body=ctx.build_body(site.function_body_block(), SugarRole.STATEMENT),
            site=site,
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
        return self._reduce_defaults(self.defaults, ctx)

    def _reduce_defaults(
        self, remaining: tuple[SugarBody, ...], ctx: object
    ) -> Outcome:
        if remaining:
            head, *rest = remaining
            return head.reduce(ctx).and_then(
                lambda _value: self._reduce_defaults(tuple(rest), ctx)
            )
        return self._reduce_kwonly_defaults(self.kwonly_defaults, ctx)

    def _reduce_kwonly_defaults(
        self, remaining: tuple[SugarBody | None, ...], ctx: object
    ) -> Outcome:
        if remaining:
            head, *rest = remaining
            if head is None:
                return self._reduce_kwonly_defaults(tuple(rest), ctx)
            return head.reduce(ctx).and_then(
                lambda _value: self._reduce_kwonly_defaults(tuple(rest), ctx)
            )
        return self._finish(ctx)

    def _finish(self, ctx: object) -> Outcome:
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

    def walk_children(self):
        return (
            *self.defaults,
            *(default for default in self.kwonly_defaults if default is not None),
            self.body,
        )
