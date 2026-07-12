from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class CallResultCallSugar(Sugar, role=SugarRole.TERM):
    """A call through the value returned by another call.

    ``factory()(arg)`` first reduces ``factory()`` through the existing call
    owner. That result is the callable address and rides first in the same
    receiver-first coordinate used by MethodCallSugar and SubscriptCallSugar.
    Positional, keyword, and expansion arguments ride the call coordinate.
    """

    receiver: SugarBody
    args: tuple[SugarBody, ...]
    keyword_names: tuple[str, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Call"
            and site.call_func().observed == "Call"
        )

    @classmethod
    def new(cls, site, ctx) -> "CallResultCallSugar":
        positional = tuple(
            ctx.build_body(arg, SugarRole.TERM) for arg in site.call_args()
        )
        keyword_names: list[str] = []
        keyword_bodies: list[SugarBody] = []
        for keyword in site.call_keywords():
            name = keyword.keyword_arg_name()
            keyword_names.append(name if name is not None else "**")
            keyword_bodies.append(
                ctx.build_body(keyword.keyword_value(), SugarRole.TERM)
            )
        return cls(
            receiver=ctx.build_body(site.call_func(), SugarRole.TERM),
            args=(*positional, *keyword_bodies),
            keyword_names=tuple(keyword_names),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n" "    constructed = type(z)(z)\n" "    return 1\n\n"
        return _call_pair(
            name="call_result_call_return",
            owner_sugar="CallResultCallSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
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

        from sugar_lift_py_tests.floor import CallSiteValue, ObjectValue
        from sugar_lift_py_tests.ir import ctor

        receiver, *arguments = accumulated
        if isinstance(receiver, ObjectValue):
            return receiver.call_method_value(
                "__call__", tuple(arguments), owner=type(self).__name__,
                blame=str(self.site), ctx=ctx,
            )

        return Complete(
            CallSiteValue(
                target_name="__call__",
                arg_values=accumulated,
                parameters=self.keyword_names,
                term=ctor(
                    "call:__call__",
                    [value.to_term(owner=str(self.site)) for value in accumulated],
                ),
                body=None,
                site=self.site,
            )
        )

    def walk_children(self):
        return (self.receiver, *self.args)
