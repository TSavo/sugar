from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


class MethodCallOperation:
    pass


@dataclass(frozen=True)
class LenCallSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    """`len(<arg>)`. Reduce the argument, and ask it for its length. A concrete
    collection folds to the count; a symbolic value stays the call:len coordinate.
    Comes before CallSugar so the length floor wins over the opaque callsite."""

    arg: SugarBody
    external_target: str | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Call"
            and site.call_receiver() is None
            and site.call_target_name() == "len"
            and site.call_arg_count() == 1
            and not site.call_has_keywords()
        )

    @classmethod
    def new(cls, site, ctx) -> "LenCallSugar":
        # The single argument is factory-built (audited), never reduced here.
        imported = (ctx.from_imports or {}).get("len")
        return cls(
            arg=ctx.build_body(site.call_args()[0], SugarRole.TERM),
            external_target=f"{imported[0]}.{imported[1]}" if imported else None,
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # A concrete list folds its length: the truthful twin rides 3, the lying
        # twin asserts 4 -- the pair proves the lift discriminates on the count.
        prefix = "def A(z):\n    xs = [1, 2, 3]\n    return len(xs)\n\n"
        return _call_pair(
            name="len_return",
            owner_sugar="LenCallSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 3\n",
            lying=prefix + "def test_a():\n    assert A(5) == 4\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce the argument, and ask it for its length.
        from sugar_lift_py_tests.floor import ObjectValue

        if self.external_target is not None:
            from sugar_lift_py_tests.floor import SymbolicValue
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import Complete
            return self.arg.reduce(ctx).and_then(
                lambda value: Complete(SymbolicValue(ctor(
                    f"call:{self.external_target}",
                    [value.to_term(owner=str(self.site))],
                )))
            )

        return self.arg.reduce(ctx).and_then(lambda value: self._finish(value, ctx))

    def _finish(self, value, ctx):
        from sugar_lift_py_tests.floor import ObjectValue

        if isinstance(value, ObjectValue):
            return value.call_method_value(
                "__len__", (), owner=type(self).__name__, blame=str(self.site), ctx=ctx
            )
        from sugar_lift_py_tests.floor import ArrayLiteral, OpaqueOpCallsite, TermValue
        from sugar_lift_py_tests.outcome import Complete

        if ctx.record_operation is not None:
            ctx.record_operation(
                owner="BuiltinCallSugar",
                method_name="call_method_with",
                operation=MethodCallOperation(),
            )
        computed = TermValue(len(value.items)) if isinstance(value, ArrayLiteral) else None
        if computed is None and hasattr(value, "elements"):
            computed = TermValue(len(value.elements))
        if computed is None and type(value).__name__ == "StringValue":
            computed = TermValue(len(value.value))
        return Complete(OpaqueOpCallsite(callee="len", arg=value, computed=computed))

    def walk_children(self):
        return (self.arg,)
