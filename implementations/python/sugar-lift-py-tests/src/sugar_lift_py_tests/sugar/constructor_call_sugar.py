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
        methods=methods,
        class_fields=_class_fields(class_site, ctx),
    )


def _strategy_from_init(
    site,
    ctx,
    target: str,
    init,
    *,
    methods=(),
    class_fields=(),
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
        class_fields=class_fields,
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
    base_name = base_coordinate
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
        return _strategy_from_init(
            site,
            ctx,
            target,
            init,
            methods=methods,
            class_fields=_class_fields(class_site, ctx),
        )
    return None


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
