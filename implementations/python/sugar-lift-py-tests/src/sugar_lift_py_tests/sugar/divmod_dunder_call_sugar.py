from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ObjectValue
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class DivmodDunderCallSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    left: SugarBody
    right: SugarBody
    site: object = field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Call"
            and site.call_receiver() is None
            and site.call_target_name() == "divmod"
            and site.call_arg_count() == 2
            and not site.call_has_keywords()
        )

    @classmethod
    def new(cls, site, ctx):
        left, right = site.call_args()
        return cls(
            ctx.build_body(left, SugarRole.TERM),
            ctx.build_body(right, SugarRole.TERM),
            site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "class Box:\n    def __divmod__(self, other):\n        return 1\n\ndef A():\n    return divmod(Box(), 2)\n\n"
        return _call_pair(
            name="divmod_dunder_return",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A() == 1\n",
            lying=prefix + "def test_a():\n    assert A() == 2\n",
        )

    def desugar(self, ctx=None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: self._finish(left, right, ctx)
            )
        )

    def _finish(self, left, right, ctx):
        from sugar_lift_py_tests.floor import GuardedValue
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        for value, replace_left in ((left, True), (right, False)):
            if isinstance(value, GuardedValue):

                def finish(branch):
                    return (
                        self._finish(branch, right, ctx)
                        if replace_left
                        else self._finish(left, branch, ctx)
                    )

                true_outcome = finish(value.when_true)
                if isinstance(true_outcome, Incomplete):
                    return true_outcome.guarded(value.guard)
                false_outcome = finish(value.when_false)
                if isinstance(false_outcome, Incomplete):
                    return false_outcome.guarded(not_(value.guard))
                return Complete(
                    GuardedValue(value.guard, true_outcome.value, false_outcome.value)
                )
        if isinstance(left, ObjectValue) and left.has_method("__divmod__"):
            return left.call_method_value(
                "__divmod__",
                (right,),
                owner=type(self).__name__,
                blame=self.site,
                ctx=ctx,
            )
        if isinstance(right, ObjectValue) and right.has_method("__rdivmod__"):
            return right.call_method_value(
                "__rdivmod__",
                (left,),
                owner=type(self).__name__,
                blame=self.site,
                ctx=ctx,
            )
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor

        return Complete(
            CallSiteValue(
                target_name="divmod",
                arg_values=(left, right),
                parameters=(),
                term=ctor(
                    "call:divmod",
                    [
                        left.to_term(owner=str(self.site)),
                        right.to_term(owner=str(self.site)),
                    ],
                    symbol_kind="builtin",
                ),
                body=None,
                site=self.site,
            )
        )

    def walk_children(self):
        return (self.left, self.right)
