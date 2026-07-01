from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.operations import (
    MethodCallOperation,
    StrCoercionOperation,
    perform_operation,
)
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
            and site.call_target_name() in _OWNED_BUILTIN_CALLS
            and site.call_arg_count() == 1
        )

    @classmethod
    def build(cls, site, ctx) -> Sugar:
        if not cls.owns(site):
            raise TypeError("BuiltinCallSugar claim built an unsupported builtin call")
        if _call_is_context_bound(site, ctx):
            from sugar_lift_py_tests.sugar.call_sugar import CallSugar

            return CallSugar.build(site, ctx)
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
        method_name = _BUILTIN_DUNDER_METHODS.get(self.name)
        if method_name is not None:
            return perform_operation(
                owner="BuiltinCallSugar",
                blame=self.blame,
                receiver=argument,
                method_name="call_method_with",
                operation=MethodCallOperation(
                    name=method_name,
                    arguments=(),
                    owner="BuiltinCallSugar",
                    blame=self.blame,
                ),
                ctx=ctx,
            )
        raise TypeError(f"write more Sugar for builtin call `{self.name}`")


_BUILTIN_DUNDER_METHODS = {
    "len": "__len__",
    "hash": "__hash__",
}
_OWNED_BUILTIN_CALLS = frozenset({"str", *_BUILTIN_DUNDER_METHODS})


def _call_is_context_bound(site, ctx) -> bool:
    target = site.call_target_name()
    if target is None:
        return False
    import_target = site.call_import_target_name(
        getattr(ctx, "import_aliases", {}) or {},
        getattr(ctx, "from_imports", {}) or {},
    )
    if import_target is not None:
        return True
    resolver = getattr(ctx, "name_resolver", None) or {}
    return target in resolver
