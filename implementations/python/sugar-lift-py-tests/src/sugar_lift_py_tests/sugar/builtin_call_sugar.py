from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import StringValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class BuiltinCallSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    name: str
    argument: SugarBody

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Call"
            and not site.call_is_method_call()
            and not site.call_has_keywords()
            and site.call_target_name() == "str"
            and site.call_arg_count() == 1
        )

    @classmethod
    def build(cls, site, ctx) -> "BuiltinCallSugar":
        if not cls.owns(site):
            raise TypeError("BuiltinCallSugar claim built an unsupported builtin call")
        return cls(
            name=site.call_target_name(),
            argument=ctx.build_body(site.call_args()[0], SugarRole.TERM),
        )

    def desugar(self, ctx) -> Outcome:
        argument_outcome = self.argument.reduce(ctx)
        if isinstance(argument_outcome, Incomplete):
            return argument_outcome
        argument = complete_value(argument_outcome, owner="BuiltinCallSugar argument")
        if self.name == "str":
            if isinstance(argument, StringValue):
                return Complete(argument)
            if isinstance(argument, TermValue):
                return Complete(StringValue(str(argument.value)))
            return Complete(
                SymbolicValue(
                    ctor(
                        "py.str",
                        [
                            floor_to_term(
                                argument, owner="BuiltinCallSugar str argument"
                            )
                        ],
                    )
                )
            )
        raise TypeError(f"write more Sugar for builtin call `{self.name}`")
