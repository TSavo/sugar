from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class StatementFunctionDefSugar(Sugar, role=SugarRole.STATEMENT):
    """An executable ``def`` binds a named callable without reducing its body."""

    name: str
    signature: tuple[tuple[str, str], ...]
    decorators: tuple[SugarBody, ...]
    positional_defaults: tuple[SugarBody, ...]
    keyword_only_defaults: tuple[SugarBody | None, ...]
    body: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "FunctionDef"

    @classmethod
    def new(cls, site, ctx) -> "StatementFunctionDefSugar":
        return cls(
            name=getattr(site.node, "_sugar_bridge_name", site.function_name()),
            signature=site.function_binding_signature(),
            decorators=tuple(
                ctx.build_body(decorator, SugarRole.TERM)
                for decorator in site.function_decorators()
            ),
            positional_defaults=tuple(
                ctx.build_body(default, SugarRole.TERM)
                for default in site.function_defaults()
            ),
            keyword_only_defaults=tuple(
                None if default is None else ctx.build_body(default, SugarRole.TERM)
                for default in site.function_keyword_only_defaults()
            ),
            body=ctx.build_body(site.function_body_block(), SugarRole.STATEMENT),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    def inner(x):\n"
            "        return x\n"
            "    return inner(z)\n\n"
        )
        return _call_pair(
            name="statement_function_def_return",
            owner_sugar="StatementFunctionDefSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self._reduce_decorators(self.decorators, (), ctx)

    def _reduce_decorators(self, remaining, accumulated, ctx) -> Outcome:
        if remaining:
            head, *rest = remaining
            return head.reduce(ctx).and_then(
                lambda value: self._reduce_decorators(
                    tuple(rest), (*accumulated, value), ctx
                )
            )
        return self._reduce_defaults(self.positional_defaults, (), accumulated, ctx)

    def _reduce_defaults(self, remaining, accumulated, decorators, ctx) -> Outcome:
        if remaining:
            head, *rest = remaining
            return head.reduce(ctx).and_then(
                lambda value: self._reduce_defaults(
                    tuple(rest), (*accumulated, value), decorators, ctx
                )
            )
        return self._reduce_keyword_only_defaults(
            self.keyword_only_defaults, (), accumulated, decorators, ctx
        )

    def _reduce_keyword_only_defaults(
        self, remaining, accumulated, positional_defaults, decorators, ctx
    ) -> Outcome:
        if remaining:
            head, *rest = remaining
            if head is None:
                return self._reduce_keyword_only_defaults(
                    tuple(rest),
                    (*accumulated, None),
                    positional_defaults,
                    decorators,
                    ctx,
                )
            return head.reduce(ctx).and_then(
                lambda value: self._reduce_keyword_only_defaults(
                    tuple(rest),
                    (*accumulated, value),
                    positional_defaults,
                    decorators,
                    ctx,
                )
            )
        return self._construct_callable(
            positional_defaults, accumulated, decorators, ctx
        )

    def _construct_callable(
        self, positional_defaults, keyword_only_defaults, decorators, ctx
    ) -> Outcome:
        from sugar_lift_py_tests.floor import FunctionCallable
        from sugar_lift_py_tests.sugar.block_sugar import BlockSugar
        from sugar_lift_py_tests.sugar.install_source_dig import (
            SequentialDigBody,
            _contextualized_dig_body,
        )

        callable_body = self.body
        if isinstance(self.body.sugar, BlockSugar):
            callable_body = _contextualized_dig_body(
                SugarBody(
                    sugar=SequentialDigBody(self.body.sugar.statements),
                    role=SugarRole.TERM,
                ),
                ctx,
            )
        return Complete(
            FunctionCallable(
                name=self.name,
                parameters=tuple(name for name, _kind in self.signature),
                parameter_kinds=tuple(kind for _name, kind in self.signature),
                positional_defaults=positional_defaults,
                keyword_only_defaults=keyword_only_defaults,
                decorators=decorators,
                body=callable_body,
            )
        )

    def walk_children(self):
        return (
            *self.decorators,
            *self.positional_defaults,
            *(default for default in self.keyword_only_defaults if default is not None),
            self.body,
        )
