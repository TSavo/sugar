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
from sugar_lift_py_tests.sugar.constructor_strategy import (
    ConstructorStrategy,
    RuntimeConstructorStrategy,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditStatus


@dataclass(frozen=True)
class ConstructorCallSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    strategy: ConstructorStrategy | RuntimeConstructorStrategy

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
        class_site = SourceFragment.from_node(node, ctx.filename)
        if _has_exact_exception_ancestry(class_site, ctx):
            from sugar_lift_py_tests.sugar.call_sugar import CallSugar

            # ClassDefSugar binds the exact LocalExceptionClassValue before this
            # deferred call reduces. Keep exception construction on that typed
            # temporal route instead of fabricating an ordinary object.
            return CallSugar.new(site, ctx, exact_exception_name=target)
        return cls(_strategy(site, ctx, target, class_site))

    @classmethod
    def witnesses(cls):
        prefix = "class Box:\n    def __init__(self, x):\n        self.x = x\n\ndef A():\n    return Box(1).x\n\n"
        exception_prefix = (
            "class LocalError(Exception):\n"
            "    pass\n\n"
            "def B(z):\n"
            "    if z < 0:\n"
            '        raise LocalError("neg")\n'
            "    return z\n\n"
        )
        return (
            _call_pair(
                name="constructor_field_return",
                owner_sugar=cls.__name__,
                truthful=prefix + "def test_a():\n    assert A() == 1\n",
                lying=prefix + "def test_a():\n    assert A() == 2\n",
            ),
            _call_pair(
                name="local_exception_class_raise",
                owner_sugar=cls.__name__,
                truthful=exception_prefix + "def test_b():\n    assert B(5) == 5\n",
                lying=exception_prefix + "def test_b():\n    assert B(5) == 6\n",
            ),
        )

    def desugar(self, ctx=None) -> Outcome:
        return self.strategy.emit(self, ctx)


def _panic(site, observed: str, requested: str, fix: str):
    info = FactoryGapInfo(
        owner="ConstructorCallSugar",
        blame=site,
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
            blame=site,
            selected=None,
            candidates=[],
            message=info.message,
        ),
    )


def _has_exact_exception_ancestry(class_site, ctx, seen: frozenset[str] = frozenset()):
    from sugar_lift_py_tests.floor import (
        BuiltinExceptionClassValue,
        ExceptionClassValue,
        ImportAliasValue,
    )

    resolver = ctx.name_resolver or {}
    for base in class_site.class_bases():
        if base.observed != "Name":
            continue
        name = base.name_id()
        if name in seen:
            continue
        resolved = resolver.get(name)
        if resolved is None:
            bound = ctx.temporal.value_if_bound(name)
            if type(bound) in (BuiltinExceptionClassValue, ExceptionClassValue):
                return True
            if isinstance(bound, ImportAliasValue) and isinstance(
                bound.resolved_value, ExceptionClassValue
            ):
                return True
            continue
        resolved_site = SourceFragment.from_node(resolved, ctx.filename)
        if resolved_site.observed == "ClassDef" and _has_exact_exception_ancestry(
            resolved_site,
            ctx,
            seen | {name},
        ):
            return True
    return False


def _strategy(
    site, ctx, target: str, class_site
) -> ConstructorStrategy | RuntimeConstructorStrategy:
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
        generated = _generated_strategy(site, ctx, target, class_site, methods)
        if generated is not None:
            return generated
        if class_site.class_bases():
            return _runtime_strategy(
                site,
                ctx,
                target,
                "inherited constructor runtime boundary: Python must resolve "
                f"{target}.__new__/__init__ through its base classes",
            )
        if site.call_arg_count() != 0:
            return _arity_strategy(site, ctx, target, 0, 0)
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
    if not init.function_has_simple_positional_params():
        return _runtime_strategy(
            site,
            ctx,
            target,
            "constructor signature runtime boundary: variadic, positional-only, "
            f"or keyword-only binding for {target} is not statically constructed",
        )
    constructor_params = params[1:]
    min_args, max_args = init.function_positional_arity()
    min_args -= 1
    max_args -= 1
    supplied = site.call_arg_count()
    if not min_args <= supplied <= max_args:
        return _arity_strategy(site, ctx, target, min_args, max_args)
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
        return _runtime_strategy(
            site,
            ctx,
            target,
            "effectful constructor runtime boundary: "
            f"{target}.__init__ contains {stmt.observed} at {stmt}",
        )
    arguments = [ctx.build_body(arg, SugarRole.TERM) for arg in site.call_args()]
    missing = max_args - supplied
    if missing:
        defaults = init.function_defaults()
        arguments.extend(
            ctx.build_body(default, SugarRole.TERM) for default in defaults[-missing:]
        )
    return ConstructorStrategy(
        class_name=target,
        fields=tuple(fields),
        parameters=constructor_params,
        arguments=tuple(arguments),
        methods=methods,
        class_fields=_class_fields(class_site, ctx),
        identity=site.blame,
    )


def _generated_strategy(
    site, ctx, target, class_site, methods
) -> ConstructorStrategy | RuntimeConstructorStrategy | None:
    decorators = class_site.class_decorators()
    exact_dataclass = (
        len(decorators) == 1
        and decorators[0].observed == "Name"
        and decorators[0].name_id() == "dataclass"
        and not class_site.class_bases()
    )
    exact_namedtuple = not decorators and class_site.class_base_names() in (
        ("NamedTuple",),
        ("typing.NamedTuple",),
    )
    if not exact_dataclass and not exact_namedtuple:
        return None

    annotated = []
    for statement in class_site.class_body():
        if statement.observed == "AnnAssign" and statement.annassign_value() is None:
            annotated.append(statement)
            continue
        if (
            statement.observed == "Expr"
            and statement.expr_value().observed == "PrimitiveLiteral"
            and isinstance(statement.expr_value().literal_value(), str)
        ):
            continue
        return _runtime_strategy(
            site,
            ctx,
            target,
            "generated constructor runtime boundary: "
            f"{target} contains non-field statement {statement.observed}",
        )

    expected = len(annotated)
    if site.call_arg_count() != expected:
        return _arity_strategy(site, ctx, target, expected, expected)
    parameters = tuple(statement.annassign_target_id() for statement in annotated)
    return ConstructorStrategy(
        class_name=target,
        fields=tuple(
            (
                name,
                ctx.build_body(statement.annassign_target(), SugarRole.TERM),
            )
            for name, statement in zip(parameters, annotated, strict=True)
        ),
        parameters=parameters,
        arguments=tuple(
            ctx.build_body(argument, SugarRole.TERM) for argument in site.call_args()
        ),
        methods=methods,
        class_fields=_class_fields(class_site, ctx),
        identity=site.blame,
    )


def _runtime_strategy(
    site, ctx, target: str, reason: str
) -> RuntimeConstructorStrategy:
    return RuntimeConstructorStrategy(
        class_name=target,
        arguments=tuple(
            ctx.build_body(argument, SugarRole.TERM) for argument in site.call_args()
        ),
        site=site,
        reason=reason,
    )


def _arity_strategy(
    site, ctx, target: str, minimum: int, maximum: int
) -> RuntimeConstructorStrategy:
    return RuntimeConstructorStrategy(
        class_name=target,
        arguments=tuple(
            ctx.build_body(argument, SugarRole.TERM) for argument in site.call_args()
        ),
        site=site,
        reason=(
            f"constructor arity type boundary: {target} requires "
            f"{minimum}..{maximum} positional arguments, got {site.call_arg_count()}"
        ),
        arity_error=True,
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
