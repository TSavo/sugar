from __future__ import annotations

from dataclasses import dataclass, replace

from sugar_lift_py_tests.claim import SugarCatalog, SugarClaim, SugarRole
from sugar_lift_py_tests.factory import (
    FactoryAuditRow,
    FactoryGapInfo,
    GapKind,
    factory_panic,
)
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import ObjectMethodValue
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.sugar.constructor_strategy import (
    ConstructorStrategy,
    RuntimeConstructorStrategy,
    SourceBodyConstructorStrategy,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditStatus


@dataclass(frozen=True)
class ConstructorCallSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    strategy: (
        ConstructorStrategy | RuntimeConstructorStrategy | SourceBodyConstructorStrategy
    )

    @staticmethod
    def recognize_initializer_call(
        site, *, receiver_name: str, declared_bases: frozenset[str] = frozenset()
    ):
        from sugar_lift_py_tests.recognition.remaining_semantics import (
            RemainingSemanticRecognition,
        )

        return RemainingSemanticRecognition.initializer_call_site(
            site,
            receiver_name=receiver_name,
            declared_bases=declared_bases,
        )

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
        bytesio_prefix = (
            "from io import BytesIO\n"
            "from numpy._utils import asbytes\n"
            "\n"
            "class TextIO(BytesIO):\n"
            "    def __init__(self, s=''):\n"
            "        BytesIO.__init__(self, asbytes(s))\n"
            "\n"
            "    def marker(self):\n"
            "        return 7\n"
            "\n"
        )
        inherited_bytesio_prefix = (
            "from io import BytesIO\n"
            "\n"
            "class RandomReader(BytesIO):\n"
            "    def marker(self):\n"
            "        return 7\n"
            "\n"
        )
        source_body_prefix = (
            "class IndexType:\n"
            "    def __init__(self, dtype):\n"
            "        name = f'index({dtype})'\n"
            "        self.name = name\n"
            "\n"
            "def D():\n"
            "    return IndexType('int64').name\n"
            "\n"
        )
        super_source_body_prefix = (
            "class Type:\n"
            "    def __init__(self, name):\n"
            "        self.name = name\n"
            "\n"
            "class IndexType(Type):\n"
            "    def __init__(self, dtype):\n"
            "        name = f'index({dtype})'\n"
            "        self.dtype = dtype\n"
            "        super().__init__(name)\n"
            "\n"
            "def F():\n"
            "    return IndexType('int64').name\n"
            "\n"
        )
        asserted_source_body_prefix = (
            "class Checked:\n"
            "    def __init__(self):\n"
            "        assert True\n"
            "        self.value = 1\n"
            "\n"
            "def E():\n"
            "    return Checked().value\n"
            "\n"
        )
        if_source_body_prefix = (
            "class Gate:\n"
            "    def __init__(self, flag, value):\n"
            "        if flag:\n"
            "            self.value = value\n"
            "        else:\n"
            "            self.value = 0\n"
            "\n"
            "def G():\n"
            "    return Gate(True, 7).value\n"
            "\n"
        )
        import_source_body_prefix = (
            "class Bound:\n"
            "    def __init__(self):\n"
            "        import math\n"
            "        self.tag = 7\n"
            "\n"
            "def H():\n"
            "    return Bound().tag\n"
            "\n"
        )
        pass_source_body_prefix = (
            "class Empty:\n"
            "    def __init__(self):\n"
            "        pass\n"
            "\n"
            "    def marker(self):\n"
            "        return 7\n"
            "\n"
            "def I():\n"
            "    return Empty().marker()\n"
            "\n"
        )
        explicit_base_prefix = (
            "from io import StringIO\n"
            "\n"
            "class MarkedText(StringIO):\n"
            "    def __init__(self, marker):\n"
            "        self.marker = marker\n"
            "        StringIO.__init__(self)\n"
            "\n"
            "def J():\n"
            "    return MarkedText('evidence').marker\n"
            "\n"
        )
        zero_arg_self_method_prefix = (
            "class Ready:\n"
            "    def __init__(self, x):\n"
            "        self.x = x\n"
            "        self._ready()\n"
            "\n"
            "    def _ready(self):\n"
            "        self.flag = 1\n"
            "\n"
            "def K():\n"
            "    return Ready(7).flag\n"
            "\n"
        )
        super_setattr_prefix = (
            "class CheckedCall:\n"
            "    def __init__(self, f):\n"
            '        super().__setattr__("f", f)\n'
            "\n"
            "def L():\n"
            "    return CheckedCall('callable').f\n"
            "\n"
        )
        ordinary_call_prefix = (
            "def prepare(value):\n"
            "    return value\n"
            "\n"
            "class Prepared:\n"
            "    def __init__(self, value):\n"
            "        prepare(value)\n"
            "        self.value = value\n"
            "\n"
            "def M():\n"
            "    return Prepared(7).value\n"
            "\n"
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
            _call_pair(
                name="source_bytesio_constructor",
                owner_sugar=cls.__name__,
                truthful=bytesio_prefix
                + "def test_c():\n    assert TextIO('seeded').marker() == 7\n",
                lying=bytesio_prefix
                + "def test_c():\n    assert TextIO('seeded').marker() == 8\n",
                family="source-native-base-constructor",
            ),
            _call_pair(
                name="inherited_bytesio_constructor",
                owner_sugar=cls.__name__,
                truthful=inherited_bytesio_prefix
                + "def test_inherited():\n"
                + "    assert RandomReader(b'seeded').marker() == 7\n",
                lying=inherited_bytesio_prefix
                + "def test_inherited():\n"
                + "    assert RandomReader(b'seeded').marker() == 8\n",
                family="source-native-base-constructor",
            ),
            _call_pair(
                name="source_body_constructor_local_assignment",
                owner_sugar=cls.__name__,
                truthful=source_body_prefix
                + "def test_source_body():\n"
                + "    assert D() == 'index(int64)'\n",
                lying=source_body_prefix
                + "def test_source_body():\n"
                + "    assert D() == 'index(float64)'\n",
                family="source-body-constructor",
            ),
            _call_pair(
                name="source_body_constructor_super_init",
                owner_sugar=cls.__name__,
                truthful=super_source_body_prefix
                + "def test_super_source_body():\n"
                + "    assert F() == 'index(int64)'\n",
                lying=super_source_body_prefix
                + "def test_super_source_body():\n"
                + "    assert F() == 'index(float64)'\n",
                family="source-body-constructor",
            ),
            _call_pair(
                name="source_body_constructor_asserted",
                owner_sugar=cls.__name__,
                truthful=asserted_source_body_prefix
                + "def test_asserted_source_body():\n"
                + "    assert E() == 1\n",
                lying=asserted_source_body_prefix
                + "def test_asserted_source_body():\n"
                + "    assert E() == 2\n",
                family="source-body-constructor",
            ),
            _call_pair(
                name="source_body_constructor_if_branch",
                owner_sugar=cls.__name__,
                truthful=if_source_body_prefix
                + "def test_if_source_body():\n"
                + "    assert G() == 7\n",
                lying=if_source_body_prefix
                + "def test_if_source_body():\n"
                + "    assert G() == 8\n",
                family="source-body-constructor",
            ),
            _call_pair(
                name="source_body_constructor_import_bind",
                owner_sugar=cls.__name__,
                truthful=import_source_body_prefix
                + "def test_import_source_body():\n"
                + "    assert H() == 7\n",
                lying=import_source_body_prefix
                + "def test_import_source_body():\n"
                + "    assert H() == 8\n",
                family="source-body-constructor",
            ),
            _call_pair(
                name="source_body_constructor_pass_only",
                owner_sugar=cls.__name__,
                truthful=pass_source_body_prefix
                + "def test_pass_source_body():\n"
                + "    assert I() == 7\n",
                lying=pass_source_body_prefix
                + "def test_pass_source_body():\n"
                + "    assert I() == 8\n",
                family="source-body-constructor",
            ),
            _call_pair(
                name="source_body_constructor_explicit_base_initializer",
                owner_sugar=cls.__name__,
                truthful=explicit_base_prefix
                + "def test_explicit_base():\n"
                + "    assert J() == 'evidence'\n",
                lying=explicit_base_prefix
                + "def test_explicit_base():\n"
                + "    assert J() == 'suppressed'\n",
                family="source-body-constructor",
            ),
            _call_pair(
                name="source_body_constructor_zero_arg_self_method",
                owner_sugar=cls.__name__,
                truthful=zero_arg_self_method_prefix
                + "def test_zero_arg_self_method():\n"
                + "    assert K() == 1\n",
                lying=zero_arg_self_method_prefix
                + "def test_zero_arg_self_method():\n"
                + "    assert K() == 0\n",
                family="source-body-constructor",
            ),
            _call_pair(
                name="source_body_constructor_super_setattr",
                owner_sugar=cls.__name__,
                truthful=super_setattr_prefix
                + "def test_super_setattr():\n"
                + "    assert L() == 'callable'\n",
                lying=super_setattr_prefix
                + "def test_super_setattr():\n"
                + "    assert L() == 'suppressed'\n",
                family="source-body-constructor",
            ),
            _call_pair(
                name="source_body_constructor_ordinary_call",
                owner_sugar=cls.__name__,
                truthful=ordinary_call_prefix
                + "def test_ordinary_call():\n"
                + "    assert M() == 7\n",
                lying=ordinary_call_prefix
                + "def test_ordinary_call():\n"
                + "    assert M() == 8\n",
                family="source-body-constructor",
            ),
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
                bound.resolve_value(), ExceptionClassValue
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
) -> ConstructorStrategy | RuntimeConstructorStrategy | SourceBodyConstructorStrategy:
    if site.call_has_keywords():
        _panic(
            site,
            f"{target}(...)",
            "positional constructor arguments",
            f"add keyword constructor binding for `{target}`",
        )
    construction_key = f"constructor-methods:{target}"
    if construction_key in ctx.building:
        _panic(
            site,
            "recursive-constructor-method",
            f"finite constructor method graph for `{target}`",
            "construct recursive constructor method coordinates without eagerly "
            "rebuilding the same class",
        )
    methods = _methods(
        class_site,
        replace(ctx, building=ctx.building | {construction_key}),
    )
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
            return _inherited_strategy(site, ctx, target, class_site, methods)
        if site.call_arg_count() != 0:
            return _arity_strategy(site, ctx, target, 0, 0)
        return ConstructorStrategy(
            class_name=target,
            fields=(),
            methods=methods,
            class_fields=_class_fields(class_site, ctx),
            identity=site.blame,
        )
    return _strategy_from_init(
        site,
        ctx,
        target,
        init,
        class_site=class_site,
        methods=methods,
        class_fields=_class_fields(class_site, ctx),
    )


def _strategy_from_init(
    site,
    ctx,
    target: str,
    init,
    *,
    class_site=None,
    methods=(),
    class_fields=(),
    allow_source_body_fallback=False,
) -> ConstructorStrategy | RuntimeConstructorStrategy:
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
    bytesio = _source_bytesio_strategy(
        site,
        ctx,
        target,
        init=init,
        class_site=class_site,
        methods=methods,
        class_fields=class_fields,
        parameters=constructor_params,
        max_args=max_args,
        supplied=supplied,
    )
    if bytesio is not None:
        return bytesio
    if _source_initializer_requires_body_reduction(
        init,
        params[0],
        class_site=class_site,
        ctx=ctx,
    ):
        source_strategy = _source_body_constructor_strategy(
            site,
            ctx,
            target,
            init,
            methods,
            class_fields,
            class_site=class_site,
        )
        if source_strategy is not None:
            return source_strategy
    fields = []
    for stmt in init.function_body():
        if (
            stmt.observed == "Expr"
            and stmt.expr_value().observed == "Constant"
            and isinstance(stmt.expr_value().literal_value(), str)
        ):
            continue
        if stmt.observed == "Pass":
            # Exact no-op: empty body and pass-before-fields are field-only
            # constructors (MyTz-shaped), not RuntimeEffect weakenings.
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
        if allow_source_body_fallback:
            return _runtime_strategy(
                site,
                ctx,
                target,
                "source initializer requires ordinary statement construction: "
                f"{target}.__init__ contains {stmt.observed} at {stmt}",
            )
        _panic(
            site,
            f"{target}.__init__ contains {stmt.observed}",
            "constructed source initializer",
            f"construct `{target}.__init__` statement {stmt.observed} exactly "
            "or leave this constructor loud",
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
        class_fields=class_fields,
        identity=site.blame,
    )


def _source_initializer_requires_body_reduction(
    init,
    receiver_name: str,
    *,
    class_site,
    ctx,
) -> bool:
    """Admit the exact ordinary-statement initializer subset.

    The field-only fast path cannot carry a local assignment into a later
    ``self`` assignment, nor branch/import/raise control. Route that decidable
    data flow through the existing source-body constructor.

    Admitted non-field statements: local assignment, annotated self bind,
    assert, if, raise, import, import-from, exact ``super().__init__(...)``,
    authenticated ``DeclaredImportedBase.__init__(self, ...)``, exact zero-arg
    ``self.method()`` (dug or stay loud), and pass (no-op). Arbitrary
    expression calls stay loud.
    """

    requires_body_reduction = False
    declared_bases = _authenticated_initializer_bases(class_site, ctx)
    for statement in init.function_body():
        if (
            statement.observed == "Expr"
            and statement.expr_value().observed == "Constant"
            and isinstance(statement.expr_value().literal_value(), str)
        ):
            continue
        if statement.observed == "Pass":
            # No-op support; field-only still handles pass-only / pass+fields.
            continue
        if statement.observed == "Assign":
            targets = statement.assign_targets()
            if len(targets) != 1:
                return False
            target = targets[0]
            if target.observed == "Name":
                requires_body_reduction = True
                continue
            if (
                statement.assign_target_attribute_receiver_name() == receiver_name
                and statement.assign_target_attribute_name() is not None
            ):
                continue
            return False
        if (
            statement.observed == "AnnAssign"
            and statement.annassign_value() is not None
            and statement.annassign_target().observed == "Attribute"
            and statement.annassign_target().dotted_expr_name() is not None
            and statement.annassign_target().dotted_expr_name().partition(".")[0]
            == receiver_name
        ):
            requires_body_reduction = True
            continue
        if statement.observed == "Assert":
            requires_body_reduction = True
            continue
        if statement.observed in {"If", "Raise", "Import", "ImportFrom"}:
            # Branch, exceptional exit, and module bind are ordinary dig
            # statements. Dig constructs them or stays loud — never empty-success.
            requires_body_reduction = True
            continue
        initializer_call = statement.initializer_call_site(
            receiver_name=receiver_name,
            declared_bases=declared_bases,
        )
        if initializer_call is not None:
            # The factory grammar boundary authenticated the initializer call.
            # Dig constructs it or stays loud; no expression is skipped.
            requires_body_reduction = True
            continue
        return False
    return requires_body_reduction


def _source_bytesio_strategy(
    site,
    ctx,
    target,
    init,
    class_site,
    methods,
    class_fields,
    parameters,
    max_args,
    supplied,
):
    """Construct the exact native BytesIO state seeded by NumPy ``asbytes``."""
    if class_site is None:
        return None
    bases = class_site.class_bases()
    if (
        len(bases) != 1
        or bases[0].observed != "Name"
        or bases[0].name_id() != "BytesIO"
        or _import_target_for_name(ctx, "BytesIO") not in {"io.BytesIO", "_io.BytesIO"}
    ):
        return None
    statements = tuple(
        statement
        for statement in init.function_body()
        if not (
            statement.observed == "Expr"
            and statement.expr_value().observed == "Constant"
            and isinstance(statement.expr_value().literal_value(), str)
        )
    )
    if len(statements) != 1 or statements[0].observed != "Expr":
        return None
    call = statements[0].expr_value()
    if call.observed != "Call" or call.call_has_keywords():
        return None
    if call.call_qualified_target_name() != "BytesIO.__init__":
        return None
    call_args = call.call_args()
    init_params = tuple(init.function_params())
    if (
        len(call_args) != 2
        or not init_params
        or call_args[0].observed != "Name"
        or call_args[0].name_id() != init_params[0]
    ):
        return None
    initial = call_args[1]
    if (
        initial.observed != "Call"
        or initial.call_target_name() != "asbytes"
        or initial.call_has_keywords()
        or len(initial.call_args()) != 1
    ):
        return None
    from sugar_lift_py_tests.factory.native_shape import (
        NativeShape,
        recognize_native_call,
    )

    if (
        recognize_native_call(_import_target_for_name(ctx, "asbytes"))
        is not NativeShape.BYTES_COERCER
    ):
        return None
    arguments = [ctx.build_body(arg, SugarRole.TERM) for arg in site.call_args()]
    missing = max_args - supplied
    if missing:
        defaults = init.function_defaults()
        arguments.extend(
            ctx.build_body(default, SugarRole.TERM) for default in defaults[-missing:]
        )
    return ConstructorStrategy(
        class_name=target,
        fields=(
            (
                "__bytesio_buffer__",
                ctx.build_body(initial, SugarRole.TERM),
            ),
        ),
        parameters=parameters,
        arguments=tuple(arguments),
        methods=methods,
        class_fields=class_fields,
        identity=site.blame,
    )


def _import_target_for_name(ctx, name: str) -> str | None:
    from sugar_lift_py_tests.floor import ImportAliasValue

    bound = ctx.temporal.value_if_bound(name)
    if bound is not None:
        return bound.import_target if isinstance(bound, ImportAliasValue) else None
    imported = (ctx.from_imports or {}).get(name)
    if imported is None:
        return None
    module, attr = imported
    return f"{module}.{attr}" if module else attr


def _authenticated_initializer_bases(class_site, ctx) -> frozenset[str]:
    """Declared imported bases eligible for explicit ``Base.__init__`` calls."""
    if class_site is None:
        return frozenset()
    coordinates = []
    for base in class_site.class_bases():
        coordinate = base.dotted_expr_name()
        if coordinate is None:
            continue
        import_target = _import_target_for_name(ctx, coordinate.partition(".")[0])
        if import_target is None or import_target in {"io.BytesIO", "_io.BytesIO"}:
            # BytesIO owns a stricter evidence-bearing constructor recognizer.
            continue
        coordinates.append(coordinate)
    return frozenset(coordinates)


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
            and statement.expr_value().observed == "Constant"
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
    site, ctx, target: str, reason: str, *, runtime_operand=None
) -> RuntimeConstructorStrategy:
    return RuntimeConstructorStrategy(
        class_name=target,
        arguments=tuple(
            ctx.build_body(argument, SugarRole.TERM) for argument in site.call_args()
        ),
        site=site,
        reason=reason,
        runtime_operand=(
            ctx.build_body(runtime_operand, SugarRole.TERM)
            if runtime_operand is not None
            else None
        ),
    )


def _inherited_strategy(site, ctx, target: str, class_site, methods=()):
    bases = class_site.class_bases()
    if len(bases) != 1:
        return _multi_base_inherited_strategy(site, ctx, target, class_site, methods)
    base = bases[0]
    base_coordinate = base.dotted_expr_name()
    if base_coordinate is None:
        return _runtime_strategy(
            site,
            ctx,
            target,
            "inherited constructor runtime boundary: runtime-selected base; Python must "
            f"resolve {target}.__new__/__init__ from that runtime operand",
            runtime_operand=base,
        )
    inherited_bytesio = _inherited_bytesio_strategy(
        site,
        ctx,
        target,
        class_site,
        methods,
        base,
    )
    if inherited_bytesio is not None:
        return inherited_bytesio
    base_name = base_coordinate
    mro = _static_constructor_mro(target, class_site, ctx)
    if mro is not None:
        return _strategy_from_static_mro(site, ctx, target, class_site, methods, mro)
    resolved = (ctx.name_resolver or {}).get(base_name)
    if resolved is None:
        from sugar_lift_py_tests.floor import ImportAliasValue, SymbolicValue

        bound = (
            ctx.temporal.value_if_bound(base_name) if base.observed == "Name" else None
        )
        if isinstance(bound, SymbolicValue):
            return _runtime_strategy(
                site,
                ctx,
                target,
                "inherited constructor runtime boundary: runtime-selected base; "
                f"Python must resolve {target}.__new__/__init__ from `{base_name}`",
                runtime_operand=base,
            )
        if isinstance(bound, ImportAliasValue) and bound.import_target is not None:
            from sugar_lift_py_tests.sugar.install_source_dig import (
                resolve_install_source_class_method,
            )

            init = resolve_install_source_class_method(bound.import_target, "__init__")
            if init is not None:
                return _strategy_from_init(
                    site,
                    ctx,
                    target,
                    init,
                    methods=methods,
                    class_fields=_class_fields(class_site, ctx),
                )
        _panic(
            site,
            f"{target}({base_name})",
            "statically resolved inherited constructor",
            f"dig the class definition for `{base_name}` and construct its "
            f"inherited `__new__`/`__init__`, or leave this call as a loud panic",
        )
    resolved_site = SourceFragment.from_node(resolved, ctx.filename)
    if resolved_site.observed != "ClassDef":
        _panic(
            site,
            f"{target}({base_name})",
            "statically resolved inherited constructor",
            f"`{base_name}` must resolve to a ClassDef before `{target}` can construct",
        )
    return _strategy(site, ctx, target, resolved_site)


def _inherited_bytesio_strategy(site, ctx, target, class_site, methods, base):
    """Carry the exact one-argument ``io.BytesIO`` inherited constructor seed."""
    has_local_new = any(
        statement.binds_name_anywhere("__new__")
        for statement in class_site.class_body()
    )
    if (
        base.observed != "Name"
        or class_site.class_decorators()
        or class_site.class_keywords()
        or has_local_new
        or (ctx.name_resolver or {}).get(base.name_id()) is not None
        or _import_target_for_name(ctx, base.name_id())
        not in {"io.BytesIO", "_io.BytesIO"}
        or site.call_arg_count() != 1
    ):
        return None
    return ConstructorStrategy(
        class_name=target,
        fields=(
            (
                "__bytesio_buffer__",
                ctx.build_body(site.call_args()[0], SugarRole.TERM),
            ),
        ),
        methods=methods,
        class_fields=_class_fields(class_site, ctx),
        identity=site.blame,
    )


def _base_type_coordinate(base):
    """Static type coordinate for a class base, peeling GenericAlias subscripts.

    ``MutableMapping[str, T]`` is the same MRO head as ``MutableMapping``;
    only the origin type participates in C3. Runtime-selected bases return None.
    """
    current = base
    while current.observed == "Subscript":
        current = current.subscript_receiver()
    return current.dotted_expr_name()


def _mro_entry_key(entry):
    kind = entry[0]
    if kind == "local":
        return ("local", entry[1])
    return ("import", entry[1])


def _c3_merge(sequences):
    """C3 linearization merge. Returns a list of entries, or None if inconsistent."""
    seqs = [list(sequence) for sequence in sequences]
    result = []
    while True:
        nonempty = [seq for seq in seqs if seq]
        if not nonempty:
            return result
        candidate = None
        for seq in nonempty:
            head = seq[0]
            head_key = _mro_entry_key(head)
            if any(
                _mro_entry_key(item) == head_key
                for other in nonempty
                for item in other[1:]
            ):
                continue
            candidate = head
            break
        if candidate is None:
            return None
        result.append(candidate)
        candidate_key = _mro_entry_key(candidate)
        for seq in seqs:
            if seq and _mro_entry_key(seq[0]) == candidate_key:
                del seq[0]


def _static_mro_for_named_base(name: str, ctx, stack: frozenset[str]):
    """Resolve one base name to its static MRO entry list, or None if undecidable."""
    if name in stack:
        return None
    resolved = (ctx.name_resolver or {}).get(name)
    if resolved is not None:
        resolved_site = SourceFragment.from_node(resolved, ctx.filename)
        if resolved_site.observed == "ClassDef":
            return _static_constructor_mro(name, resolved_site, ctx, stack=stack)

    from sugar_lift_py_tests.floor import ImportAliasValue, SymbolicValue

    if "." in name:
        head, rest = name.split(".", 1)
        bound = ctx.temporal.value_if_bound(head)
        if isinstance(bound, ImportAliasValue) and bound.import_target is not None:
            return _static_mro_for_import(f"{bound.import_target}.{rest}", stack)
        return None
    bound = ctx.temporal.value_if_bound(name)
    if isinstance(bound, SymbolicValue):
        return None
    if isinstance(bound, ImportAliasValue) and bound.import_target is not None:
        return _static_mro_for_import(bound.import_target, stack)
    return None


def _static_mro_for_import(import_target: str, stack: frozenset[str]):
    """Exact C3 MRO for an imported class, derived from its resolved source bases."""
    if import_target in stack:
        return None
    if import_target == "builtins.object":
        return (("import", import_target),)

    from sugar_lift_py_tests.sugar.install_source_dig import (
        resolve_install_source_class_bases,
    )

    direct_bases = resolve_install_source_class_bases(import_target)
    if direct_bases is None:
        return None
    next_stack = stack | {import_target}
    base_mros = []
    base_heads = []
    for base in direct_bases:
        base_mro = _static_mro_for_import(base, next_stack)
        if base_mro is None:
            return None
        base_mros.append(base_mro)
        base_heads.append(base_mro[0])
    root = ("import", import_target)
    if not base_mros:
        return (root,)
    merged = _c3_merge([list(mro) for mro in base_mros] + [base_heads])
    if merged is None:
        return None
    return (root, *merged)


def _static_constructor_mro(class_name: str, class_site, ctx, *, stack=frozenset()):
    """Exact C3 MRO for a ClassDef when every base is a static type coordinate.

    Each entry is either ``("local", name, class_site)`` or ``("import", import_target)``.
    Returns None when any base is undecidable or the linearization is inconsistent.
    """
    if class_name in stack:
        return None
    next_stack = stack | {class_name}
    base_mros = []
    base_heads = []
    for base in class_site.class_bases():
        coordinate = _base_type_coordinate(base)
        if coordinate is None:
            return None
        base_mro = _static_mro_for_named_base(coordinate, ctx, next_stack)
        if base_mro is None:
            return None
        base_mros.append(base_mro)
        base_heads.append(base_mro[0])
    root = ("local", class_name, class_site)
    if not base_mros:
        return (root,)
    merged = _c3_merge([list(mro) for mro in base_mros] + [base_heads])
    if merged is None:
        return None
    return (root, *merged)


def _constructor_from_mro_entry(site, ctx, target: str, class_site, methods, entry):
    """If this MRO class defines ``__init__``, build its strategy; else None to continue."""
    if entry[0] == "local":
        _kind, _name, entry_site = entry
        init = next(
            (
                stmt
                for stmt in entry_site.class_body()
                if stmt.observed == "FunctionDef" and stmt.function_name() == "__init__"
            ),
            None,
        )
        if init is None:
            return None
        return _strategy_from_init(
            site,
            ctx,
            target,
            init,
            methods=methods,
            class_fields=_class_fields(class_site, ctx),
        )
    if entry[0] == "import":
        from sugar_lift_py_tests.sugar.install_source_dig import (
            resolve_install_source_class_method,
        )

        _kind, import_target = entry
        init = resolve_install_source_class_method(import_target, "__init__")
        if init is None:
            return None
        class_fields = _class_fields(class_site, ctx)
        strategy = _strategy_from_init(
            site,
            ctx,
            target,
            init,
            methods=methods,
            class_fields=class_fields,
            allow_source_body_fallback=True,
        )
        if (
            isinstance(strategy, RuntimeConstructorStrategy)
            and strategy.runtime_operand is None
            and not strategy.arity_error
        ):
            source_strategy = _source_body_constructor_strategy(
                site,
                ctx,
                target,
                init,
                methods,
                class_fields,
                class_site=class_site,
            )
            if source_strategy is not None:
                return source_strategy
        return strategy
    return None


def _source_body_constructor_strategy(
    site, ctx, target: str, init, methods, class_fields, *, class_site=None
):
    """Construct an initializer through the ordinary statement door.

    Exact ``super().__init__(...)`` statements are expanded into the static
    base ``__init__`` body so constructed self state includes base fields
    (e.g. ``Type.__init__`` binding ``self.name``). Exact zero-arg
    ``self.method()`` statements expand into the local dug method body so
    method-side ``self.*`` rebinds are recovered. Unresolvable super or
    undiggable self-methods remain unconstructed — no empty-success
    SupportValue arm.
    """
    if class_fields or not init.function_has_simple_positional_params():
        return None
    params = tuple(init.function_params())
    if not params:
        return None
    min_args, max_args = init.function_positional_arity()
    min_args -= 1
    max_args -= 1
    supplied = site.call_arg_count()
    if not min_args <= supplied <= max_args:
        return None

    from sugar_lift_py_tests.sugar.install_source_dig import build_dig_body

    initializer_ctx = _constructor_initializer_factory_context(
        init=init,
        class_site=class_site,
        target=target,
        ctx=ctx,
        self_name=params[0],
    )
    if initializer_ctx is None:
        return None
    body = build_dig_body(
        init,
        initializer_ctx,
        oracle_variant=f"constructor-initializer-calls:{target}",
    )
    if body is None:
        return None
    arguments = [ctx.build_body(arg, SugarRole.TERM) for arg in site.call_args()]
    missing = max_args - supplied
    if missing:
        defaults = init.function_defaults()
        arguments.extend(
            ctx.build_body(default, SugarRole.TERM) for default in defaults[-missing:]
        )
    return SourceBodyConstructorStrategy(
        class_name=target,
        body=body,
        parameters=params,
        arguments=tuple(arguments),
        methods=methods,
        identity=site.blame,
        has_assertion=any(
            statement.observed == "Assert" for statement in init.function_body()
        ),
    )


@dataclass(frozen=True)
class SuperInitApply:
    """Apply a dug base ``__init__`` body at an exact ``super().__init__(...)``.

    Not a catalog sugar: ConstructorCallSugar synthesizes it when the static
    MRO resolves a source base initializer. ``desugar`` recovers the base
    ``self.*`` rebinds as ``ScopeRebinds`` so the constructor scope keeps the
    exact object state.
    """

    base_body: object
    base_parameters: tuple[str, ...]
    arguments: tuple
    self_name: str
    site: object

    def desugar(self, ctx=None) -> Outcome:
        from sugar_lift_py_tests.floor.call_site_value import _ctx_with_curried_args
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
        from sugar_lift_py_tests.outcome import Complete, Incomplete, complete_value
        from sugar_lift_py_tests.sugar.install_source_dig import ContextualizedDigBody

        if ctx is None:
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=str(self.site),
                observed="super().__init__",
                requested="constructor self scope for base initializer",
                fix="apply super().__init__ only inside a constructor scope",
            )
        self_value = ctx.temporal.value_if_bound(self.self_name)
        if self_value is None:
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=str(self.site),
                observed=f"unbound {self.self_name}",
                requested="constructor self for super().__init__",
                fix=f"bind `{self.self_name}` before expanding super().__init__",
            )
        values = []
        for argument in self.arguments:
            outcome = argument.reduce(ctx)
            if isinstance(outcome, Incomplete):
                return outcome
            values.append(complete_value(outcome, owner="super().__init__ argument"))
        if len(self.base_parameters) != 1 + len(values):
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=str(self.site),
                observed=(
                    f"super().__init__ arity {len(values)} for base params "
                    f"{self.base_parameters}"
                ),
                requested="matching super().__init__ argument count",
                fix="construct the exact base __init__ arity or leave super loud",
            )
        contextualized = self.base_body.sugar
        if not isinstance(contextualized, ContextualizedDigBody):
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=str(self.site),
                observed=type(contextualized).__name__,
                requested="dug base __init__ body",
                fix="dig the static base __init__ before expanding super()",
            )
        curried = _ctx_with_curried_args(
            ctx, self.base_parameters, (self_value, *values)
        )
        final_ctx, assertions, terminal = contextualized.initializer_scope_after(
            curried
        )
        if terminal is not None:
            return Complete(terminal)
        if assertions:
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=str(self.site),
                observed="base __init__ assertion",
                requested="assertion-free super().__init__ expansion",
                fix=(
                    "construct super() base initializers that assert through the "
                    "constructor assertion face, or leave this super loud"
                ),
            )
        base_self = self.base_parameters[0]
        field_prefix = f"{base_self}."
        bindings = tuple(
            (
                f"{self.self_name}.{binding.name.removeprefix(field_prefix)}",
                binding.value,
            )
            for binding in final_ctx.temporal.bindings
            if binding.name.startswith(field_prefix)
        )
        return Complete(ScopeRebinds(bindings))


@dataclass(frozen=True)
class ObjectInitApply:
    """The exact zero-argument ``object.__init__`` no-op."""

    site: object

    def desugar(self, ctx=None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor import SupportValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(SupportValue())


@dataclass(frozen=True)
class OrdinaryInitializerCallApply:
    """Evaluate a factory-recognized plain call used as an initializer statement."""

    value: SugarBody
    site: object

    def desugar(self, ctx=None) -> Outcome:
        from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap
        from sugar_lift_py_tests.floor import (
            CallSiteValue,
            ExceptionalExitValue,
            GuardedValue,
            SupportValue,
        )
        from sugar_lift_py_tests.outcome import Complete, Incomplete, complete_value

        outcome = self.value.reduce(ctx)
        if isinstance(outcome, Incomplete):
            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=str(self.site),
                observed=type(outcome.effect).__name__,
                requested="decidable ordinary initializer call",
                fix="construct the call result or leave the initializer loud",
            )
        value = complete_value(outcome, owner="ConstructorCallSugar")
        if not isinstance(value, CallSiteValue) or value.body is None:
            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=str(self.site),
                observed=type(value).__name__,
                requested="source-backed ordinary initializer call",
                fix="attach and reduce the callable body or leave the initializer loud",
            )
        reduced = value._dig_floor_or_none(
            ctx,
            owner="ConstructorCallSugar.ordinary_initializer_call",
        )
        if reduced is None:
            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=str(self.site),
                observed=f"opaque {value.target_name} call",
                requested="decidable ordinary initializer call",
                fix="construct the callable body result or leave the initializer loud",
            )
        if isinstance(reduced, ExceptionalExitValue):
            return Complete(reduced)
        if isinstance(reduced, GuardedValue):
            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=str(self.site),
                observed="guarded ordinary initializer call result",
                requested="decidable ordinary initializer call",
                fix="resolve the call's guarded exit or leave the initializer loud",
            )
        return Complete(SupportValue())


@dataclass(frozen=True)
class SuperSetAttrApply:
    """Construct exact ``super().__setattr__("name", value)`` self state."""

    attribute_name: str
    value: object
    self_name: str
    site: object

    def desugar(self, ctx=None) -> Outcome:
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
        from sugar_lift_py_tests.outcome import Complete, Incomplete, complete_value

        if ctx is None:
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=str(self.site),
                observed='super().__setattr__("name", value)',
                requested="constructor self scope for ground attribute binding",
                fix="apply super().__setattr__ only inside a constructor scope",
            )
        if ctx.temporal.value_if_bound(self.self_name) is None:
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=str(self.site),
                observed=f"unbound {self.self_name}",
                requested="constructor self for super().__setattr__",
                fix=f"bind `{self.self_name}` before applying super().__setattr__",
            )
        outcome = self.value.reduce(ctx)
        if isinstance(outcome, Incomplete):
            return outcome
        value = complete_value(outcome, owner="super().__setattr__ value")
        return Complete(
            ScopeRebinds(((f"{self.self_name}.{self.attribute_name}", value),))
        )


@dataclass(frozen=True)
class SelfMethodApply:
    """Apply a dug zero-arg ``self.method()`` body inside a source initializer.

    Not a catalog sugar: ConstructorCallSugar synthesizes it when the local
    class defines a diggable zero-arg method. ``desugar`` recovers method-side
    ``self.*`` rebinds as ``ScopeRebinds`` so the constructor scope keeps the
    exact object state. Undiggable methods never reach this door.
    """

    method_body: object
    method_parameters: tuple[str, ...]
    self_name: str
    method_name: str
    site: object

    def desugar(self, ctx=None) -> Outcome:
        from sugar_lift_py_tests.floor.call_site_value import _ctx_with_curried_args
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.install_source_dig import ContextualizedDigBody

        if ctx is None:
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=str(self.site),
                observed=f"self.{self.method_name}()",
                requested="constructor self scope for zero-arg method",
                fix="apply self.method() only inside a constructor scope",
            )
        self_value = ctx.temporal.value_if_bound(self.self_name)
        if self_value is None:
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=str(self.site),
                observed=f"unbound {self.self_name}",
                requested=f"constructor self for self.{self.method_name}()",
                fix=(
                    f"bind `{self.self_name}` before expanding "
                    f"self.{self.method_name}()"
                ),
            )
        if len(self.method_parameters) != 1:
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=str(self.site),
                observed=(
                    f"self.{self.method_name}() arity for params "
                    f"{self.method_parameters}"
                ),
                requested="zero-arg method self parameter only",
                fix=(
                    "construct only exact zero-arg self.method() shapes or leave "
                    "this call loud"
                ),
            )
        contextualized = self.method_body.sugar
        if not isinstance(contextualized, ContextualizedDigBody):
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=str(self.site),
                observed=type(contextualized).__name__,
                requested="dug zero-arg self.method body",
                fix=(
                    f"dig `{self.method_name}` before expanding "
                    f"self.{self.method_name}()"
                ),
            )
        curried = _ctx_with_curried_args(ctx, self.method_parameters, (self_value,))
        final_ctx, assertions, terminal = contextualized.initializer_scope_after(
            curried
        )
        if terminal is not None:
            return Complete(terminal)
        if assertions:
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame=str(self.site),
                observed=f"self.{self.method_name}() assertion",
                requested="assertion-free zero-arg self.method expansion",
                fix=(
                    "construct self.method() bodies that assert through the "
                    "constructor assertion face, or leave this call loud"
                ),
            )
        method_self = self.method_parameters[0]
        field_prefix = f"{method_self}."
        bindings = tuple(
            (
                f"{self.self_name}.{binding.name.removeprefix(field_prefix)}",
                binding.value,
            )
            for binding in final_ctx.temporal.bindings
            if binding.name.startswith(field_prefix)
        )
        return Complete(ScopeRebinds(bindings))


def _resolve_local_class_method(class_site, method_name: str):
    """Local ClassDef FunctionDef for ``method_name``, or None."""
    if class_site is None:
        return None
    return next(
        (
            statement
            for statement in class_site.class_body()
            if statement.observed == "FunctionDef"
            and statement.function_name() == method_name
        ),
        None,
    )


def _resolve_super_init_for_class(class_site, target: str, ctx):
    """First defining ``__init__`` after ``target`` on the static MRO, or a tag.

    Returns:
      - a FunctionDef SourceFragment for a source base ``__init__``
      - ``"object"`` when only ``object.__init__`` remains (empty apply)
      - ``None`` when super cannot be resolved statically
    """
    if class_site is None:
        return None
    mro = _static_constructor_mro(target, class_site, ctx)
    if mro is None:
        # Single local base still admits super when C3 is unavailable for other
        # reasons only if the sole base is a local ClassDef with diggable init.
        bases = class_site.class_bases()
        if len(bases) != 1:
            return None
        base = bases[0]
        if base.observed != "Name":
            return None
        resolved = (ctx.name_resolver or {}).get(base.name_id())
        if resolved is None:
            from sugar_lift_py_tests.floor import ImportAliasValue

            bound = ctx.temporal.value_if_bound(base.name_id())
            if isinstance(bound, ImportAliasValue) and bound.import_target is not None:
                from sugar_lift_py_tests.sugar.install_source_dig import (
                    resolve_install_source_class_method,
                )

                init = resolve_install_source_class_method(
                    bound.import_target, "__init__"
                )
                return init if init is not None else None
            return None
        resolved_site = SourceFragment.from_node(resolved, ctx.filename)
        if resolved_site.observed != "ClassDef":
            return None
        init = next(
            (
                statement
                for statement in resolved_site.class_body()
                if statement.observed == "FunctionDef"
                and statement.function_name() == "__init__"
            ),
            None,
        )
        return init if init is not None else "object"

    for entry in mro[1:]:
        if entry[0] == "local":
            _kind, _name, entry_site = entry
            init = next(
                (
                    statement
                    for statement in entry_site.class_body()
                    if statement.observed == "FunctionDef"
                    and statement.function_name() == "__init__"
                ),
                None,
            )
            if init is not None:
                return init
            continue
        if entry[0] == "import":
            _kind, import_target = entry
            if import_target in {"builtins.object", "object"}:
                return "object"
            from sugar_lift_py_tests.sugar.install_source_dig import (
                resolve_install_source_class_method,
            )

            init = resolve_install_source_class_method(import_target, "__init__")
            if init is not None:
                return init
            continue
    return "object"


def _constructor_initializer_factory_context(
    *,
    init,
    class_site,
    target: str,
    ctx,
    self_name: str,
):
    """Install the constructor-only initializer-call claim in the factory."""
    from sugar_lift_py_tests.sugar.expr_sugar import ExprSugar
    from sugar_lift_py_tests.sugar.install_source_dig import build_dig_body

    declared_bases = _authenticated_initializer_bases(class_site, ctx)
    call_sites = tuple(
        statement.initializer_call_site(
            receiver_name=self_name,
            declared_bases=declared_bases,
        )
        for statement in init.function_body()
    )

    super_init = None
    if any(call is not None and call.kind == "super" for call in call_sites):
        resolved = _resolve_super_init_for_class(class_site, target, ctx)
        if resolved == "object":
            super_init = ("object", (), None)
        elif resolved is not None and resolved.function_has_simple_positional_params():
            parameters = tuple(resolved.function_params())
            body = build_dig_body(resolved, ctx) if parameters else None
            if body is not None:
                super_init = ("source", parameters, body)

    method_applies: dict[str, tuple[object, tuple[str, ...]]] = {}
    for call in call_sites:
        if call is None or call.kind != "self_method" or call.target is None:
            continue
        method = _resolve_local_class_method(class_site, call.target)
        if method is None or not method.function_has_simple_positional_params():
            continue
        parameters = tuple(method.function_params())
        min_args, max_args = method.function_positional_arity()
        if (
            min_args != 1
            or max_args != 1
            or len(parameters) != 1
            or any(
                statement.observed == "Return" for statement in method.function_body()
            )
        ):
            continue
        body = build_dig_body(method, ctx)
        if body is not None:
            method_applies[call.target] = (body, parameters)

    if any(
        call is not None
        and (
            call.kind == "super"
            and super_init is None
            or call.kind == "self_method"
            and call.target not in method_applies
        )
        for call in call_sites
    ):
        # The statement door owns only calls it can construct. Unresolved
        # initializer calls fall back to the constructor's original loud arm.
        return None

    def recognized(site):
        call = site.initializer_call_site(
            receiver_name=self_name,
            declared_bases=declared_bases,
        )
        if call is None:
            return False
        if call.kind == "ordinary_call":
            return True
        if call.kind == "explicit_base":
            return True
        if call.kind == "super_setattr":
            return call.target is not None
        if call.kind == "super":
            if super_init is None:
                return False
            kind, parameters, _body = super_init
            return (
                call.call.call_arg_count() == 0
                if kind == "object"
                else len(parameters) == 1 + call.call.call_arg_count()
            )
        return call.kind == "self_method" and call.target in method_applies

    def construct(site, build_ctx):
        call = site.initializer_call_site(
            receiver_name=self_name,
            declared_bases=declared_bases,
        )
        if call is None:
            raise AssertionError("initializer claim constructed an unrecognized site")
        if call.kind == "ordinary_call":
            return OrdinaryInitializerCallApply(
                value=build_ctx.build_body(call.call, SugarRole.TERM),
                site=site,
            )
        if call.kind == "explicit_base":
            return ExprSugar.new(site, build_ctx)
        if call.kind == "super_setattr":
            assert call.target is not None
            arguments = call.call.call_args()
            assert len(arguments) == 2
            return SuperSetAttrApply(
                attribute_name=call.target,
                value=build_ctx.build_body(arguments[1], SugarRole.TERM),
                self_name=self_name,
                site=site,
            )
        if call.kind == "super":
            assert super_init is not None
            kind, parameters, base_body = super_init
            arguments = tuple(
                build_ctx.build_body(argument, SugarRole.TERM)
                for argument in call.call.call_args()
            )
            if kind == "object":
                assert not arguments
                return ObjectInitApply(site=site)
            assert len(parameters) == 1 + len(arguments)
            return SuperInitApply(
                base_body=base_body,
                base_parameters=parameters,
                arguments=arguments,
                self_name=self_name,
                site=site,
            )
        assert call.target is not None
        method_body, parameters = method_applies[call.target]
        return SelfMethodApply(
            method_body=method_body,
            method_parameters=parameters,
            self_name=self_name,
            method_name=call.target,
            site=site,
        )

    claim = SugarClaim(
        name="ConstructorInitializerCallSugar",
        role=SugarRole.STATEMENT,
        owns=recognized,
        comes_before=("ExprSugar",),
        new=construct,
    )
    return replace(ctx, catalog=SugarCatalog((*ctx.catalog.claims, claim)))


def _native_imported_base_targets(class_site, ctx):
    """Resolve direct dotted bases whose module artifact is a native extension."""
    import importlib.machinery
    import importlib.util

    from sugar_lift_py_tests.floor import ImportAliasValue

    targets = []
    for base in class_site.class_bases():
        coordinate = _base_type_coordinate(base)
        if coordinate is None or "." not in coordinate:
            return None
        module_name, class_name = coordinate.split(".", 1)
        bound = ctx.temporal.value_if_bound(module_name)
        if not isinstance(bound, ImportAliasValue) or bound.import_target is None:
            return None
        spec = importlib.util.find_spec(bound.import_target)
        origin = None if spec is None else spec.origin
        if origin is None or not any(
            origin.endswith(suffix) for suffix in importlib.machinery.EXTENSION_SUFFIXES
        ):
            return None
        targets.append(f"{bound.import_target}.{class_name}")
    return tuple(targets) if targets else None


def _multi_base_inherited_strategy(site, ctx, target: str, class_site, methods=()):
    """Construct the exact multiple-inheritance MRO and take the first ``__init__``.

    Undecidable bases (runtime-selected, unresolved, symbolic) stay a loud
    construction panic — never a RuntimeEffect weakening of the gap.
    """
    mro = _static_constructor_mro(target, class_site, ctx)
    if mro is None:
        native_bases = _native_imported_base_targets(class_site, ctx)
        if native_bases is not None:
            return _runtime_strategy(
                site,
                ctx,
                target,
                "native inherited constructor runtime boundary: "
                f"{target} has statically resolved extension bases "
                f"{native_bases}; the constructor result depends on its "
                "runtime arguments",
            )
        _panic(
            site,
            f"{target} bases={class_site.class_base_names()}",
            "statically resolved inherited constructor",
            f"construct the exact multiple-inheritance MRO for `{target}`",
        )
    return _strategy_from_static_mro(site, ctx, target, class_site, methods, mro)


def _strategy_from_static_mro(site, ctx, target, class_site, methods, mro):
    """Select the first constructed initializer from an exact static MRO."""
    for entry in mro[1:]:
        strategy = _constructor_from_mro_entry(
            site, ctx, target, class_site, methods, entry
        )
        if strategy is not None:
            if (
                isinstance(strategy, RuntimeConstructorStrategy)
                and strategy.runtime_operand is None
                and not strategy.arity_error
            ):
                _panic(
                    site,
                    f"{target} MRO selected {entry[1]}.__init__",
                    "statically constructed inherited constructor body",
                    f"construct `{entry[1]}.__init__` exactly or leave its "
                    "decidable body as this loud constructor gap",
                )
            return strategy
    if site.call_arg_count() != 0:
        return _arity_strategy(site, ctx, target, 0, 0)
    return ConstructorStrategy(
        class_name=target,
        fields=(),
        methods=methods,
        class_fields=_class_fields(class_site, ctx),
        identity=site.blame,
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
