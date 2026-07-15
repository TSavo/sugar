from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import (
    FactoryAuditRow,
    FactoryGapInfo,
    GapKind,
    factory_panic,
)
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import ObjectMethodValue
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.constructor_strategy import ConstructorStrategy
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditStatus


@dataclass(frozen=True)
class ConstructorCallSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    strategy: ConstructorStrategy

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Call":
            return False
        target = site.call_target_name()
        return (
            site.call_receiver() is None
            and target is not None
            and target[:1].isupper()
            and not site.call_has_keywords()
        )

    @classmethod
    def new(cls, site, ctx):
        target = site.call_target_name()
        node = (ctx.name_resolver or {}).get(target)
        if (
            node is None
            or SourceFragment.from_node(node, ctx.filename).observed != "ClassDef"
        ):
            from sugar_lift_py_tests.sugar.call_sugar import CallSugar

            return CallSugar.new(site, ctx)
        return cls(
            _strategy(site, ctx, target, SourceFragment.from_node(node, ctx.filename))
        )

    @classmethod
    def witnesses(cls):
        prefix = "class Box:\n    def __init__(self, x):\n        self.x = x\n\ndef A():\n    return Box(1).x\n\n"
        return _call_pair(
            name="constructor_field_return",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A() == 1\n",
            lying=prefix + "def test_a():\n    assert A() == 2\n",
        )

    def desugar(self, ctx=None) -> Outcome:
        return self.strategy.emit(self, ctx)


def _panic(site, observed: str, requested: str, fix: str):
    info = FactoryGapInfo(
        owner="ConstructorCallSugar",
        blame=site.blame,
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind=GapKind.CONSTRUCTOR,
    )
    factory_panic(
        info,
        FactoryAuditRow(
            role=requested,
            status=FactoryAuditStatus.FLOOR_GAP,
            observed=observed,
            blame=site.blame,
            selected=None,
            candidates=[],
            message=info.message,
        ),
    )


def _strategy(site, ctx, target: str, class_site) -> ConstructorStrategy:
    if site.call_has_keywords():
        _panic(
            site,
            f"{target}(...)",
            "positional constructor arguments",
            f"add keyword constructor binding for `{target}`",
        )
    methods = _methods(class_site, ctx)
    init = next(
        (
            stmt
            for stmt in class_site.class_body()
            if stmt.observed == "FunctionDef" and stmt.function_name() == "__init__"
        ),
        None,
    )
    if init is None:
        if site.call_arg_count() != 0:
            _panic(
                site,
                f"{target}(...)",
                "zero-arg constructor",
                f"add constructor argument binding for `{target}`",
            )
        return ConstructorStrategy(
            class_name=target,
            fields=(),
            methods=methods,
            class_fields=_class_fields(class_site, ctx),
            identity=site.blame,
        )
    params = tuple(init.function_params())
    if not params:
        _panic(
            init,
            f"{target}.__init__()",
            "constructor self parameter",
            f"add self to `{target}.__init__`",
        )
    constructor_params = params[1:]
    if len(constructor_params) != site.call_arg_count():
        _panic(
            site,
            f"{target}(...)",
            f"{len(constructor_params)} constructor arguments",
            f"add constructor argument binding for `{target}`",
        )
    fields = []
    for stmt in init.function_body():
        if (
            stmt.observed == "Expr"
            and stmt.expr_value().observed == "PrimitiveLiteral"
            and isinstance(stmt.expr_value().literal_value(), str)
        ):
            continue
        if (
            stmt.observed == "Assign"
            and stmt.assign_target_attribute_receiver_name() == params[0]
            and stmt.assign_target_attribute_name() is not None
        ):
            fields.append(
                (
                    stmt.assign_target_attribute_name(),
                    ctx.build_body(stmt.assign_value(), SugarRole.TERM),
                )
            )
            continue
        _panic(
            stmt,
            f"{target}.__init__:{stmt.observed}",
            "constructor field assignment",
            f"write constructor sugar for `{target}.__init__`",
        )
    return ConstructorStrategy(
        class_name=target,
        fields=tuple(fields),
        parameters=constructor_params,
        arguments=tuple(
            ctx.build_body(arg, SugarRole.TERM) for arg in site.call_args()
        ),
        methods=methods,
        class_fields=_class_fields(class_site, ctx),
        identity=site.blame,
    )


def _methods(class_site, ctx):
    methods = []
    for stmt in class_site.class_body():
        body = stmt.function_body() if stmt.observed == "FunctionDef" else ()
        if (
            stmt.observed == "FunctionDef"
            and stmt.function_name() != "__init__"
            and len(body) == 1
            and body[0].observed == "Return"
            and body[0].return_value() is not None
        ):
            methods.append(
                ObjectMethodValue(
                    stmt.function_name(),
                    tuple(stmt.function_params()),
                    ctx.build_body(body[0].return_value(), SugarRole.TERM),
                )
            )
    return tuple(methods)


def _class_fields(class_site, ctx):
    fields = []
    for stmt in class_site.class_body():
        if stmt.observed == "Assign" and stmt.assign_target_name() is not None:
            fields.append(
                (
                    stmt.assign_target_name(),
                    ctx.build_body(stmt.assign_value(), SugarRole.TERM),
                )
            )
    return tuple(fields)
