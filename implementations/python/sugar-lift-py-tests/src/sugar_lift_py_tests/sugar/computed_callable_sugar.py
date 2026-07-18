from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.callable_application import CallableApplication
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.recognition.call_identity import CallIdentityRecognition
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ComputedCallableSugar(Sugar, role=SugarRole.TERM):
    """Apply a callable produced by another term expression.

    The factory constructs the callable expression and all call operands first.
    Application is then floor-owned: a FunctionCallable substitutes its body,
    while a value without a callable floor remains a loud construction gap.
    """

    callable_body: SugarBody
    arguments: tuple[SugarBody, ...]
    keyword_names: tuple[str, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, fragment) -> bool:
        return CallIdentityRecognition.is_computed_callable(fragment)

    @classmethod
    def new(cls, site, ctx) -> "ComputedCallableSugar":
        positional = tuple(
            ctx.build_body(argument, SugarRole.TERM)
            for argument in site.call_args()
        )
        keyword_names: list[str] = []
        keyword_bodies: list[SugarBody] = []
        for keyword in site.call_keywords():
            keyword_names.append(keyword.keyword_arg_name() or "**")
            keyword_bodies.append(
                ctx.build_body(keyword.keyword_value(), SugarRole.TERM)
            )
        return cls(
            callable_body=ctx.build_body(site.call_function(), SugarRole.TERM),
            arguments=(*positional, *keyword_bodies),
            keyword_names=tuple(keyword_names),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def identity(value):\n"
            "    return value\n"
            "\n"
            "def zero(value):\n"
            "    return 0\n"
            "\n"
            "def A(value):\n"
            "    return (identity if True else zero)(value)\n"
            "\n"
        )
        return _call_pair(
            name="computed_callable_conditional_return",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx=None) -> Outcome:
        return self.callable_body.reduce(ctx).and_then(
            lambda callable_value: self._collect(
                callable_value, self.arguments, (), ctx
            )
        )

    def _collect(
        self,
        callable_value,
        remaining: tuple[SugarBody, ...],
        accumulated: tuple,
        ctx,
    ) -> Outcome:
        if remaining:
            head, *tail = remaining
            return head.reduce(ctx).and_then(
                lambda value: self._collect(
                    callable_value,
                    tuple(tail),
                    (*accumulated, value),
                    ctx,
                )
            )
        return CallableApplication(
            arguments=accumulated,
            keyword_names=self.keyword_names,
            site=self.site,
        ).apply(callable_value, ctx)

    def walk_children(self):
        return (self.callable_body, *self.arguments)
