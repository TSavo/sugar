from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.operations import (
    BinaryOperatorOperation,
    MethodCallOperation,
    NextOperation,
    StrCoercionOperation,
    perform_operation,
)
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import (
    builtin_len_return_witness,
    divmod_subscript_return_witness,
    format_int_return_witness,
)
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class BuiltinCallSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    name: str
    argument: SugarBody
    blame: str = "<unknown>"

    @classmethod
    def owns(cls, site) -> bool:
        if (
            site.observed != "Call"
            or site.call_has_keywords()
            or site.call_arg_count() != 1
        ):
            return False
        if site.call_is_method_call():
            return site.call_qualified_target_name() == _OPERATOR_INDEX_CALL
        return site.call_target_name() in _OWNED_BUILTIN_CALLS

    @classmethod
    def witnesses(cls):
        return builtin_len_return_witness()

    @classmethod
    def build(cls, site, ctx) -> Sugar:
        if not cls.owns(site):
            raise TypeError("BuiltinCallSugar claim built an unsupported builtin call")
        name = _owned_builtin_name(site, ctx)
        if name is None:
            from sugar_lift_py_tests.sugar.call_sugar import CallSugar

            return CallSugar.build(site, ctx)
        return cls(
            name=name,
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
                operation=StrCoercionOperation(
                    owner="BuiltinCallSugar",
                    blame=self.blame,
                ),
                ctx=ctx,
            )
        if self.name == "next":
            return perform_operation(
                owner="BuiltinCallSugar",
                blame=self.blame,
                receiver=argument,
                operation=NextOperation(
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
                operation=MethodCallOperation(
                    name=method_name,
                    arguments=(),
                    owner="BuiltinCallSugar",
                    blame=self.blame,
                ),
                ctx=ctx,
            )
        raise TypeError(f"write more Sugar for builtin call `{self.name}`")


@dataclass(frozen=True)
class DivmodBuiltinSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    left: SugarBody
    right: SugarBody
    blame: str = "<unknown>"

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Call"
            and not site.call_is_method_call()
            and not site.call_has_keywords()
            and site.call_target_name() == "divmod"
            and site.call_arg_count() == 2
        )

    @classmethod
    def witnesses(cls):
        return divmod_subscript_return_witness()

    @classmethod
    def build(cls, site, ctx) -> Sugar:
        if not cls.owns(site):
            raise TypeError(
                "DivmodBuiltinSugar claim built an unsupported builtin call"
            )
        if _call_is_context_bound(site, ctx):
            from sugar_lift_py_tests.sugar.call_sugar import CallSugar

            return CallSugar.build(site, ctx)
        left, right = site.call_args()
        return cls(
            left=ctx.build_body(left, SugarRole.TERM),
            right=ctx.build_body(right, SugarRole.TERM),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        left_outcome = self.left.reduce(ctx)
        if isinstance(left_outcome, Incomplete):
            return left_outcome
        right_outcome = self.right.reduce(ctx)
        if isinstance(right_outcome, Incomplete):
            return right_outcome
        left = complete_value(left_outcome, owner="DivmodBuiltinSugar left")
        right = complete_value(right_outcome, owner="DivmodBuiltinSugar right")
        return perform_operation(
            owner="DivmodBuiltinSugar",
            blame=self.blame,
            receiver=left,
            operation=BinaryOperatorOperation(
                operator="divmod",
                right=right,
                owner="DivmodBuiltinSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )


@dataclass(frozen=True)
class FormatBuiltinSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    argument: SugarBody
    spec: SugarBody | None
    blame: str = "<unknown>"

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Call"
            and not site.call_is_method_call()
            and not site.call_has_keywords()
            and site.call_target_name() == "format"
            and site.call_arg_count() in (1, 2)
        )

    @classmethod
    def witnesses(cls):
        return format_int_return_witness()

    @classmethod
    def build(cls, site, ctx) -> Sugar:
        if not cls.owns(site):
            raise TypeError(
                "FormatBuiltinSugar claim built an unsupported builtin call"
            )
        if _call_is_context_bound(site, ctx):
            from sugar_lift_py_tests.sugar.call_sugar import CallSugar

            return CallSugar.build(site, ctx)
        args = site.call_args()
        return cls(
            argument=ctx.build_body(args[0], SugarRole.TERM),
            spec=ctx.build_body(args[1], SugarRole.TERM) if len(args) == 2 else None,
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        argument_outcome = self.argument.reduce(ctx)
        if isinstance(argument_outcome, Incomplete):
            return argument_outcome
        argument = complete_value(argument_outcome, owner="FormatBuiltinSugar argument")
        if self.spec is None:
            spec = StringValue("")
        else:
            spec_outcome = self.spec.reduce(ctx)
            if isinstance(spec_outcome, Incomplete):
                return spec_outcome
            spec = complete_value(spec_outcome, owner="FormatBuiltinSugar spec")
        return perform_operation(
            owner="FormatBuiltinSugar",
            blame=self.blame,
            receiver=argument,
            operation=MethodCallOperation(
                name="__format__",
                arguments=(spec,),
                owner="FormatBuiltinSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )


_BUILTIN_DUNDER_METHODS = {
    "abs": "__abs__",
    "round": "__round__",
    "floor": "__floor__",
    "ceil": "__ceil__",
    "trunc": "__trunc__",
    "len": "__len__",
    "hash": "__hash__",
    "repr": "__repr__",
    "bytes": "__bytes__",
    "reversed": "__reversed__",
    "dir": "__dir__",
    "int": "__int__",
    "float": "__float__",
    "complex": "__complex__",
    "operator.index": "__index__",
}
_OPERATOR_INDEX_CALL = "operator.index"
_OWNED_BUILTIN_CALLS = frozenset(
    {
        "next",
        "str",
        *_BUILTIN_DUNDER_METHODS,
    }
) - {_OPERATOR_INDEX_CALL}


def _owned_builtin_name(site, ctx) -> str | None:
    target = site.call_target_name()
    if not site.call_is_method_call() and target in _OWNED_BUILTIN_CALLS:
        if _call_is_context_bound(site, ctx):
            return None
        return target
    if (
        site.call_qualified_target_name() == _OPERATOR_INDEX_CALL
        and _canonical_import_target(site, ctx) == _OPERATOR_INDEX_CALL
    ):
        return _OPERATOR_INDEX_CALL
    return None


def _canonical_import_target(site, ctx) -> str | None:
    return site.call_import_target_name(
        getattr(ctx, "import_aliases", {}) or {},
        getattr(ctx, "from_imports", {}) or {},
    )


def _call_is_context_bound(site, ctx) -> bool:
    target = site.call_target_name()
    if target is None:
        return False
    import_target = _canonical_import_target(site, ctx)
    if import_target is not None:
        return True
    resolver = getattr(ctx, "name_resolver", None) or {}
    return target in resolver
