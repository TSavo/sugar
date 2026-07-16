from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class SubscriptCallSugar(Sugar, role=SugarRole.TERM):
    """A call through a subscript-selected callable.

    ``dispatch[key](arg)`` first reduces ``dispatch[key]`` through the existing
    subscript floor. That resulting value is the callable address, so it rides
    first in the same receiver-first call coordinate used by MethodCallSugar.
    Keyword names and values ride after the positional coordinates. A
    ``**kwargs`` expansion uses the same explicit ``**`` parameter spelling as
    the other call-coordinate owners, so no dynamic call input is dropped.
    """

    receiver: SugarBody
    args: tuple[SugarBody, ...]
    kwargs: tuple[tuple[str, SugarBody], ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Call" and site.call_func().observed == "Subscript"

    @classmethod
    def new(cls, site, ctx) -> "SubscriptCallSugar":
        return cls(
            receiver=ctx.build_body(site.call_func(), SugarRole.TERM),
            args=tuple(ctx.build_body(arg, SugarRole.TERM) for arg in site.call_args()),
            kwargs=tuple(
                (
                    keyword.keyword_arg_name() or "**",
                    ctx.build_body(keyword.keyword_value(), SugarRole.TERM),
                )
                for keyword in site.call_keywords()
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def identity(x):\n"
            "    return x\n"
            "def A(z):\n"
            "    choices = [identity]\n"
            "    return choices[0](z)\n\n"
        )
        return _call_pair(
            name="subscript_call_return",
            owner_sugar="SubscriptCallSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.receiver.reduce(ctx).and_then(
            lambda receiver: self._collect(self.args, (receiver,), ctx)
        )

    def _collect(
        self, remaining: tuple[SugarBody, ...], accumulated: tuple, ctx: object
    ) -> Outcome:
        if remaining:
            head, *rest = remaining
            return head.reduce(ctx).and_then(
                lambda value: self._collect(tuple(rest), (*accumulated, value), ctx)
            )
        return self._collect_kwargs(self.kwargs, accumulated, (), ctx)

    def _collect_kwargs(
        self,
        remaining: tuple[tuple[str, SugarBody], ...],
        positional: tuple,
        keywords: tuple,
        ctx: object,
    ) -> Outcome:
        if remaining:
            (name, body), *rest = remaining
            return body.reduce(ctx).and_then(
                lambda value: self._collect_kwargs(
                    tuple(rest), positional, (*keywords, (name, value)), ctx
                )
            )
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor, str_const

        term_args = [value.to_term(owner=str(self.site)) for value in positional]
        term_args.extend(
            ctor("kw", [str_const(name), value.to_term(owner=str(self.site))])
            for name, value in keywords
        )

        return Complete(
            CallSiteValue(
                target_name="__call__",
                arg_values=positional,
                parameters=tuple(name for name, _ in keywords),
                term=ctor(
                    "call:__call__",
                    term_args,
                    symbol_kind="method-coordinate",
                ),
                body=None,
                site=self.site,
            )
        )

    def walk_children(self):
        return (self.receiver, *self.args, *(body for _, body in self.kwargs))
