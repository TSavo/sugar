from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ObjectValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody

_METHODS = {
    "hash": "__hash__",
    "round": "__round__",
    "floor": "__floor__",
    "ceil": "__ceil__",
    "trunc": "__trunc__",
    "int": "__int__",
    "float": "__float__",
    "complex": "__complex__",
    "next": "__next__",
    "repr": "__repr__",
    "str": "__str__",
    "bytes": "__bytes__",
    "dir": "__dir__",
    "reversed": "__reversed__",
    "external_len": "__len__",
}


class StrCoercionOperation:
    pass


@dataclass(frozen=True)
class BuiltinDunderCallSugar(
    Sugar, role=SugarRole.TERM, comes_before=("AbsCallSugar", "CallSugar")
):
    name: str
    arg: SugarBody
    external_target: str | None
    site: object = field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Call"
            and site.call_receiver() is None
            and site.call_target_name() in _METHODS
            and site.call_arg_count() == 1
            and not site.call_has_keywords()
        )

    @classmethod
    def new(cls, site, ctx):
        imported = (ctx.from_imports or {}).get(site.call_target_name())
        external_target = f"{imported[0]}.{imported[1]}" if imported else None
        return cls(
            site.call_target_name(),
            ctx.build_body(site.call_args()[0], SugarRole.TERM),
            external_target,
            site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "class Box:\n    def __hash__(self):\n        return 1\n\ndef A():\n    return hash(Box())\n\n"
        return _call_pair(
            name="builtin_dunder_hash",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A() == 1\n",
            lying=prefix + "def test_a():\n    assert A() == 2\n",
        )

    def desugar(self, ctx=None) -> Outcome:
        return self.arg.reduce(ctx).and_then(lambda value: self._finish(value, ctx))

    def _finish(self, value, ctx):
        from sugar_lift_py_tests.floor import GuardedValue
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import Incomplete

        if isinstance(value, GuardedValue):
            true_outcome = self._finish(value.when_true, ctx)
            if isinstance(true_outcome, Incomplete):
                return true_outcome.guarded(value.guard)
            false_outcome = self._finish(value.when_false, ctx)
            if isinstance(false_outcome, Incomplete):
                return false_outcome.guarded(not_(value.guard))
            return Complete(
                GuardedValue(value.guard, true_outcome.value, false_outcome.value)
            )
        if self.external_target is not None:
            from sugar_lift_py_tests.floor import SymbolicValue
            from sugar_lift_py_tests.ir import ctor

            return Complete(
                SymbolicValue(
                    ctor(
                        f"call:{self.external_target}",
                        [value.to_term(owner=str(self.site))],
                    )
                )
            )
        if isinstance(value, ObjectValue):
            return value.call_method_value(
                _METHODS[self.name],
                (),
                owner=type(self).__name__,
                blame=str(self.site),
                ctx=ctx,
            )
        if self.name == "str":
            from sugar_lift_py_tests.floor import (
                OpaqueOpCallsite,
                StringValue,
                TermValue,
            )

            if ctx.record_operation is not None:
                ctx.record_operation(
                    owner="BuiltinCallSugar",
                    method_name="str_with",
                    operation=StrCoercionOperation(),
                )
            computed = (
                StringValue(str(value.value))
                if isinstance(value, TermValue) and type(value.value) in (int, float)
                else None
            )
            return Complete(
                OpaqueOpCallsite(callee="str", arg=value, computed=computed)
            )
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor

        return Complete(
            CallSiteValue(
                self.name,
                (value,),
                (),
                ctor(f"call:{self.name}", [value.to_term(owner=str(self.site))]),
                None,
                self.site,
            )
        )

    def walk_children(self):
        return (self.arg,)
