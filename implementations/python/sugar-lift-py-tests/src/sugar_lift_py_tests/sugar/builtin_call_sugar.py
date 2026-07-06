from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.factory.build import FactoryCandidateDeclined
from sugar_lift_py_tests.floor import ObjectValue, StringValue, SymbolicValue
from sugar_lift_py_tests.operations import (
    AttributeLookupOperation,
    BinaryOperatorOperation,
    MethodCallOperation,
    NextOperation,
    StrCoercionOperation,
    perform_operation,
)
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import (
    builtin_len_return_witness,
    divmod_subscript_return_witness,
    format_int_return_witness,
)
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair, WitnessSource
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

    def _build(self, ctx) -> Outcome:
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
        if self.name == "dir":
            return _build_dir_builtin(argument, self.blame, ctx)
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
class GetattrBuiltinSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    receiver: SugarBody
    attr_name: str | None
    dynamic_name_observed: str | None
    blame: str = "<unknown>"

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Call"
            and not site.call_is_method_call()
            and not site.call_has_keywords()
            and site.call_target_name() == "getattr"
            and site.call_arg_count() == 2
        )

    @classmethod
    def witnesses(cls):
        return SugarWitnessPair(
            name="getattr_builtin_literal_attribute",
            owner_sugar=cls.__name__,
            family="python-builtin-getattr",
            truthful=WitnessSource(
                source=(
                    "class Box:\n"
                    "    def __init__(self):\n"
                    "        self.value = 2\n"
                    "\n"
                    "def A():\n"
                    "    return getattr(Box(), 'value')\n"
                    "\n"
                    "def test_a():\n"
                    "    assert A() == 2\n"
                ),
                expected="sat",
            ),
            lying=WitnessSource(
                source=(
                    "class Box:\n"
                    "    def __init__(self):\n"
                    "        self.value = 2\n"
                    "\n"
                    "def A():\n"
                    "    return getattr(Box(), 'value')\n"
                    "\n"
                    "def test_a():\n"
                    "    assert A() == 3\n"
                ),
                expected="unsat",
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> Sugar:
        if not cls.owns(site):
            raise TypeError(
                "GetattrBuiltinSugar claim built an unsupported getattr call"
            )
        if _call_is_context_bound(site, ctx):
            from sugar_lift_py_tests.sugar.call_sugar import CallSugar

            return CallSugar.build(site, ctx)
        receiver, name = site.call_args()
        attr_name = None
        dynamic_name_observed = name.observed
        if name.observed == "PrimitiveLiteral":
            literal = name.literal_value()
            if isinstance(literal, str):
                attr_name = literal
                dynamic_name_observed = None
        return cls(
            receiver=ctx.build_body(receiver, SugarRole.TERM),
            attr_name=attr_name,
            dynamic_name_observed=dynamic_name_observed,
            blame=site.blame,
        )

    def _build(self, ctx) -> Outcome:
        if self.attr_name is None:
            return _runtime_getattr_effect(
                self.blame,
                f"attribute name expression `{self.dynamic_name_observed}` is runtime",
            )
        receiver_outcome = self.receiver.reduce(ctx)
        if isinstance(receiver_outcome, Incomplete):
            return receiver_outcome
        receiver = complete_value(
            receiver_outcome, owner="GetattrBuiltinSugar receiver"
        )
        if isinstance(receiver, SymbolicValue):
            return _runtime_getattr_effect(
                self.blame,
                "receiver reduced to SymbolicValue; Python resolves attributes at runtime",
            )
        return perform_operation(
            owner="GetattrBuiltinSugar",
            blame=self.blame,
            receiver=receiver,
            operation=AttributeLookupOperation(
                name=self.attr_name,
                owner="GetattrBuiltinSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )


def _runtime_getattr_effect(blame: str, detail: str) -> Incomplete:
    return Incomplete(
        RuntimeEffect(
            "getattr runtime boundary: "
            f"{detail}. Python evaluates dynamic attribute access at runtime; keep "
            "this as a typed red effect until a narrower vendor-cited reduction "
            f"owns the shape. blame={blame}"
        )
    )


def _build_dir_builtin(argument, blame: str, ctx) -> Outcome:
    if isinstance(argument, ObjectValue):
        if argument.has_method("__dir__"):
            return perform_operation(
                owner="BuiltinCallSugar",
                blame=blame,
                receiver=argument,
                operation=MethodCallOperation(
                    name="__dir__",
                    arguments=(),
                    owner="BuiltinCallSugar",
                    blame=blame,
                ),
                ctx=ctx,
            )
        return _runtime_dir_effect(
            blame=blame,
            shape=f"{argument.class_name}.__dir__",
            detail=(
                "constructor-bound __dir__ is absent; Python falls back through "
                "object.__dir__ and runtime attribute inventory"
            ),
        )
    if isinstance(argument, SymbolicValue):
        return _runtime_dir_effect(
            blame=blame,
            shape="SymbolicValue.__dir__",
            detail=(
                "symbolic receiver has no static attribute inventory; Python "
                "computes dir() from runtime object state"
            ),
        )
    return perform_operation(
        owner="BuiltinCallSugar",
        blame=blame,
        receiver=argument,
        operation=MethodCallOperation(
            name="__dir__",
            arguments=(),
            owner="BuiltinCallSugar",
            blame=blame,
        ),
        ctx=ctx,
    )


def _runtime_dir_effect(*, blame: str, shape: str, detail: str) -> Incomplete:
    return Incomplete(
        RuntimeEffect(
            "dir builtin runtime boundary: "
            "crime=dir() requested a runtime attribute inventory; "
            "owner=BuiltinCallSugar; "
            f"shape={shape}; "
            f"detail={detail}; "
            "replacement=add a cited dir/object attribute-inventory floor before "
            "treating this as proof-bearing; "
            f"blame={blame}"
        )
    )


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

    def _build(self, ctx) -> Outcome:
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
            raise FactoryCandidateDeclined(
                "context-bound `format` belongs to CallSugar"
            )
        args = site.call_args()
        return cls(
            argument=ctx.build_body(args[0], SugarRole.TERM),
            spec=ctx.build_body(args[1], SugarRole.TERM) if len(args) == 2 else None,
            blame=site.blame,
        )

    def _build(self, ctx) -> Outcome:
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
        ctx.import_aliases or {},
        ctx.from_imports or {},
    )


def _call_is_context_bound(site, ctx) -> bool:
    target = site.call_target_name()
    if target is None:
        return False
    import_target = _canonical_import_target(site, ctx)
    if import_target is not None:
        return True
    resolver = ctx.name_resolver or {}
    return target in resolver
