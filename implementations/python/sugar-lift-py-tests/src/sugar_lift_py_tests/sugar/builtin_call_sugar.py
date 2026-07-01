from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.operations import StrCoercionOperation, perform_operation
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class BuiltinCallSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    name: str
    argument: SugarBody
    blame: str = "<unknown>"

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
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        argument_outcome = self.argument.reduce(ctx)
        if isinstance(argument_outcome, Incomplete):
            return argument_outcome
        argument = complete_value(argument_outcome, owner="BuiltinCallSugar argument")
        if self.name == "str":
            return perform_operation(
                owner="BuiltinCallSugar",
                blame=self.blame,
                receiver=argument,
                method_name="str_with",
                operation=StrCoercionOperation(
                    owner="BuiltinCallSugar",
                    blame=self.blame,
                ),
                ctx=ctx,
            )
        raise TypeError(f"write more Sugar for builtin call `{self.name}`")
