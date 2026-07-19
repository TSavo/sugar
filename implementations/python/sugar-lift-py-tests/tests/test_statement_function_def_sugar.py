from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    DictValue,
    FunctionCallable,
    GuardedValue,
    RaiseValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
    UniverseValue,
)
from sugar_lift_py_tests.ir import atomic, ctor, make_var, num
from sugar_lift_py_tests.idd.sugar_witness_instruments import evaluate_seed_witnesses
from sugar_lift_py_tests.outcome import Incomplete, complete_value
from sugar_lift_py_tests.sugar.keyword_call_sugar import KeywordCallSugar
from sugar_lift_py_tests.sugar.statement_function_def_sugar import (
    DEFERRED_STATEMENT_STRUCTURE_ORACLE,
    StatementFunctionDefSugar,
)


def _root_universe(source: str) -> UniverseValue:
    node = ast.parse(source).body[0]
    catalog = default_catalog()
    ctx = FactoryBuildContext(filename="nested.py", catalog=catalog)
    result = build_node(
        node,
        filename="nested.py",
        role=SugarRole("definition"),
        ctx=ctx,
    )
    value = complete_value(result.sugar.desugar(ctx), owner="nested def regression")
    assert isinstance(value, UniverseValue)
    return value


def test_statement_function_body_factory_construction_is_deferred(
    monkeypatch,
) -> None:
    root = SourceFragment.from_source(
        "def helper(value=1):\n"
        "    first = value + 1\n"
        "    second = first + 1\n"
        "    return second\n",
        "deferred.py",
    )
    function = next(
        fragment for fragment in root.walk() if fragment.observed == "FunctionDef"
    )
    catalog = default_catalog()
    ctx = FactoryBuildContext(
        filename="deferred.py",
        catalog=catalog,
        defer_function_body_construction=True,
    )
    original = FactoryBuildContext.build_body
    built: list[tuple[str, SugarRole]] = []

    def counted_build_body(self, site, role):
        built.append((site.observed, role))
        return original(self, site, role)

    monkeypatch.setattr(FactoryBuildContext, "build_body", counted_build_body)

    sugar = StatementFunctionDefSugar.new(function, ctx)
    value = complete_value(sugar.desugar(ctx), owner="deferred statement function body")

    assert isinstance(value, FunctionCallable)
    assert value.body is not None
    assert ("Block", SugarRole.STATEMENT) not in built
    assert not any(
        observed in {"Assign", "Return"} and role is SugarRole.STATEMENT
        for observed, role in built
    )


def test_deferred_statement_structure_is_memoized_by_content_identity(
    monkeypatch,
) -> None:
    """Second dig of the same deferred body reuses structure; never Incomplete/None.

    Residual reduce_body profiles after #5321 re-factory the same statement
    sites on every SequentialDigBody walk (e.g. set_module decorator bodies).
    Structure is content-addressed; reduce still runs with the live context.
    """
    root = SourceFragment.from_source(
        "def helper():\n" "    return 1\n",
        "deferred_memo.py",
    )
    function = next(
        fragment for fragment in root.walk() if fragment.observed == "FunctionDef"
    )
    ctx = FactoryBuildContext(
        filename="deferred_memo.py",
        catalog=default_catalog(),
        defer_function_body_construction=True,
    )
    DEFERRED_STATEMENT_STRUCTURE_ORACLE.clear()
    original = FactoryBuildContext.build_body
    statement_builds: list[str] = []

    def counted_build_body(self, site, role):
        if role is SugarRole.STATEMENT:
            statement_builds.append(str(getattr(site, "observed", "?")))
        return original(self, site, role)

    monkeypatch.setattr(FactoryBuildContext, "build_body", counted_build_body)

    sugar = StatementFunctionDefSugar.new(function, ctx)
    callable_value = complete_value(
        sugar.desugar(ctx), owner="deferred structure memo first bind"
    )
    assert isinstance(callable_value, FunctionCallable)
    assert callable_value.body is not None

    first = complete_value(
        callable_value.body.reduce(ctx), owner="deferred structure memo first dig"
    )
    constructs_after_first = DEFERRED_STATEMENT_STRUCTURE_ORACLE.construct_count
    builds_after_first = list(statement_builds)
    hits_after_first = DEFERRED_STATEMENT_STRUCTURE_ORACLE.hit_count

    second = complete_value(
        callable_value.body.reduce(ctx), owner="deferred structure memo second dig"
    )
    assert first == second
    # Structure constructed once per body statement identity; second dig hits.
    assert DEFERRED_STATEMENT_STRUCTURE_ORACLE.construct_count == constructs_after_first
    assert DEFERRED_STATEMENT_STRUCTURE_ORACLE.hit_count > hits_after_first
    assert statement_builds == builds_after_first
    # Never publish Incomplete/None as structure success.
    assert all(
        value is not None
        for value in DEFERRED_STATEMENT_STRUCTURE_ORACLE._table.values()
    )
    assert DEFERRED_STATEMENT_STRUCTURE_ORACLE.construct_count >= 1


def test_deferred_statement_structure_oracle_never_publishes_none() -> None:
    """None is not a complete structure; identity table stays empty."""
    DEFERRED_STATEMENT_STRUCTURE_ORACLE.clear()
    key = ("file.py", 1, 0, "Pass", "pass")
    DEFERRED_STATEMENT_STRUCTURE_ORACLE._publish(key, None)  # type: ignore[arg-type]
    assert key not in DEFERRED_STATEMENT_STRUCTURE_ORACLE._table


def test_deferred_statement_structure_never_crosses_factory_contexts() -> None:
    """Identical statement text must not reuse structure from another resolver."""

    def class_node(field_value: int) -> ast.ClassDef:
        node = ast.parse(
            "class Foo:\n"
            "    def __init__(self):\n"
            f"        self.x = {field_value}\n"
        ).body[0]
        assert isinstance(node, ast.ClassDef)
        return node

    statement = SourceFragment.from_source("return Foo()\n", "same.py").statements()[0]
    catalog = default_catalog()
    first_ctx = FactoryBuildContext(
        filename="same.py",
        catalog=catalog,
        name_resolver={"Foo": class_node(1)},
    )
    second_ctx = FactoryBuildContext(
        filename="same.py",
        catalog=catalog,
        name_resolver={"Foo": class_node(2)},
    )

    DEFERRED_STATEMENT_STRUCTURE_ORACLE.clear()
    first_body = DEFERRED_STATEMENT_STRUCTURE_ORACLE.resolve(statement, first_ctx)
    first = complete_value(first_body.reduce(first_ctx), owner="first resolver")
    second_body = DEFERRED_STATEMENT_STRUCTURE_ORACLE.resolve(statement, second_ctx)
    second = complete_value(second_body.reduce(second_ctx), owner="second resolver")

    assert "ObjectField(name='x', value=TermValue(value=1))" in repr(first)
    assert "ObjectField(name='x', value=TermValue(value=2))" in repr(second)
    assert first_body is not second_body


def test_deferred_statement_structure_rebuilds_for_temporal_and_catalog_contexts() -> None:
    """The same source fragment must rebuild for temporal/catalog twins."""
    from dataclasses import replace
    from sugar_lift_py_tests.temporal import TemporalContext

    statement = SourceFragment.from_source("return 1\n", "same.py").statements()[0]
    catalog = default_catalog()
    first_ctx = FactoryBuildContext(
        filename="same.py",
        catalog=catalog,
        temporal=TemporalContext.empty().bind_value("marker", TermValue(1)),
    )
    second_ctx = replace(
        first_ctx,
        catalog=type(catalog)(claims=tuple(reversed(tuple(catalog.claims)))),
        temporal=TemporalContext.empty().bind_value("marker", TermValue(2)),
    )

    DEFERRED_STATEMENT_STRUCTURE_ORACLE.clear()
    first_body = DEFERRED_STATEMENT_STRUCTURE_ORACLE.resolve(statement, first_ctx)
    second_body = DEFERRED_STATEMENT_STRUCTURE_ORACLE.resolve(statement, second_ctx)

    assert first_body is not second_body


def test_deferred_statement_identity_includes_enclosing_source() -> None:
    """Equal statement segments in different sources are distinct structures."""
    first_root = SourceFragment.from_source(
        "seed = 1\n" "def helper():\n" "    return seed\n",
        "same.py",
    )
    second_root = SourceFragment.from_source(
        "seed = 2\n" "def helper():\n" "    return seed\n",
        "same.py",
    )
    first_return = next(
        fragment for fragment in first_root.walk() if fragment.observed == "Return"
    )
    second_return = next(
        fragment for fragment in second_root.walk() if fragment.observed == "Return"
    )
    ctx = FactoryBuildContext(filename="same.py", catalog=default_catalog())

    first_key = DEFERRED_STATEMENT_STRUCTURE_ORACLE.identity_key(first_return, ctx)
    second_key = DEFERRED_STATEMENT_STRUCTURE_ORACLE.identity_key(second_return, ctx)

    assert first_return.blame == second_return.blame
    assert first_key != second_key


def test_nested_def_binds_named_callable_and_later_call_digs_body() -> None:
    universe = _root_universe(
        "def outer(x):\n"
        "    def inner(y):\n"
        "        return y + 1\n"
        "    return inner(x)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    dug = callsite.force_floor(
        ctx, owner="nested def regression", project_callsite=False
    )
    assert isinstance(dug, TermValue)
    assert dug.value == 6
    assert "inner" in repr(universe.record)


def test_decorated_callable_call_substitutes_through_wrapper() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def decorate(func):\n"
        "        def wrapper(value):\n"
        "            return func(value) + 1\n"
        "        return wrapper\n"
        "    @decorate\n"
        "    def doubled(value):\n"
        "        return value * 2\n"
        "    return doubled(3)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="decorated callable substitution", project_callsite=False
    ) == TermValue(7)


def test_decorated_callable_wrapper_fills_original_missing_argument() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def decorate(func):\n"
        "        def wrapper(value):\n"
        "            return func(value, 4)\n"
        "        return wrapper\n"
        "    @decorate\n"
        "    def add(value, increment):\n"
        "        return value + increment\n"
        "    return add(3)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="decorated callable curry floor", project_callsite=False
    ) == TermValue(7)


def _imported_decorator_callsite(import_target: str) -> CallSiteValue:
    from sugar_lift_py_tests.floor import ImportAliasValue
    from sugar_lift_py_tests.sugar.call_sugar import CallSugar
    from sugar_lift_py_tests.temporal import TemporalContext

    original = FunctionCallable(name="original", body=object())
    site = SourceFragment.from_source("wraps(original)\n", "nested.py").statements()[0]
    ctx = FactoryBuildContext(
        filename="nested.py",
        catalog=default_catalog(),
        temporal=(
            TemporalContext.empty()
            .bind_value(
                "wraps",
                ImportAliasValue(
                    import_target,
                    "wraps",
                    import_target=import_target,
                ),
            )
            .bind_value("original", original)
        ),
    )
    decorator = complete_value(
        CallSugar(
            target_name="wraps",
            args=(),
            keyword_names=(),
            site=site,
        )._collect((), (original,), ctx),
        owner="decorator import identity",
    )
    assert isinstance(decorator, CallSiteValue)
    return decorator


def test_authenticated_functools_wraps_preserves_wrapped_callable() -> None:
    from dataclasses import replace

    impl = FunctionCallable(name="wrapper", body=object())
    decorator = _imported_decorator_callsite("functools.wraps")
    decorated = replace(impl, decorators=(decorator,))
    assert decorated._apply_decorators(decorator.site) == impl


def test_authenticated_functools_module_wraps_carries_native_contract() -> None:
    from sugar_lift_py_tests.floor import ImportAliasValue
    from sugar_lift_py_tests.recognition.native_shape import NativeShape
    from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
    from sugar_lift_py_tests.temporal import TemporalContext

    original = FunctionCallable(name="original", body=object())
    module = ImportAliasValue("functools", "functools", import_target="functools")
    site = SourceFragment.from_source(
        "functools.wraps(original)\n", "nested.py"
    ).statements()[0]
    ctx = FactoryBuildContext(
        filename="nested.py",
        catalog=default_catalog(),
        temporal=TemporalContext.empty(),
    )
    decorator = complete_value(
        MethodCallSugar(
            method_name="wraps",
            import_target="functools.wraps",
            receiver=object(),
            args=(),
            keyword_names=(),
            site=site,
        )._collect((), (module, original), ctx),
        owner="functools module decorator identity",
    )
    assert isinstance(decorator, CallSiteValue)
    assert decorator.native_shape is NativeShape.IMPLEMENTATION_PRESERVING_DECORATOR


def test_unqualified_wraps_lookalike_stays_loud() -> None:
    from dataclasses import replace

    impl = FunctionCallable(name="wrapper", body=object())
    decorator = _imported_decorator_callsite("project.wraps")
    decorated = replace(impl, decorators=(decorator,))
    with pytest.raises(FactoryPanic) as raised:
        decorated.callsite((TermValue(3),), (), decorator.site)
    assert raised.value.info.owner == (
        "FunctionCallable decorator factory:project.wraps"
    )


def test_site_authenticated_functools_wraps_without_native_shape_stamp() -> None:
    """Corpus shape: MethodCall target_name is bare ``wraps``; site is functools.wraps.

    Nested dig often loses import_aliases, so native_shape is unset. Recognition
    re-authenticates from the decorator Call AST + defining-module imports.
    """
    import ast
    from dataclasses import replace

    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.recognition.decorator_contracts import (
        decorator_value_preserves_implementation,
    )

    source = (
        "import functools\n"
        "\n"
        "def outer(func):\n"
        "    @functools.wraps(func)\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return func(*args, **kwargs)\n"
        "    return wrapper\n"
    )
    mod = ast.parse(source)
    wraps_call = None
    for node in ast.walk(mod):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "wraps":
                wraps_call = SourceFragment.from_node(node, "mod.py", source=source)
                break
    assert wraps_call is not None

    decorator = CallSiteValue(
        target_name="wraps",
        arg_values=(FunctionCallable(name="func", body=object()),),
        parameters=(),
        term=ctor("call:wraps", [], symbol_kind="coordinate"),
        body=None,
        site=wraps_call,
        native_shape=None,
    )
    assert decorator_value_preserves_implementation(decorator) is True
    impl = FunctionCallable(name="wrapper", body=object())
    applied = replace(impl, decorators=(decorator,))._apply_decorators(wraps_call)
    assert applied == impl


def test_lookalike_attribute_wraps_without_functools_import_stays_loud() -> None:
    import ast
    from dataclasses import replace

    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.recognition.decorator_contracts import (
        decorator_value_preserves_implementation,
    )

    source = (
        "import lookalike as functools\n"
        "\n"
        "@functools.wraps(func)\n"
        "def wrapper(*args, **kwargs):\n"
        "    return func(*args, **kwargs)\n"
    )
    mod = ast.parse(source)
    wraps_call = None
    for node in ast.walk(mod):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "wraps":
                wraps_call = SourceFragment.from_node(node, "fake.py", source=source)
                break
    assert wraps_call is not None

    decorator = CallSiteValue(
        target_name="wraps",
        arg_values=(FunctionCallable(name="func", body=object()),),
        parameters=(),
        term=ctor("call:wraps", [], symbol_kind="coordinate"),
        body=None,
        site=wraps_call,
        native_shape=None,
    )
    # dotted AST name is ``functools.wraps`` but import warrants lookalike.
    # recognize_native_decorator on dotted still matches the spelling — ensure
    # lookalike module alias does NOT free-pass via bare Attribute spelling alone.
    # The site path must require the authenticated module head.
    assert decorator_value_preserves_implementation(decorator) is False
    impl = FunctionCallable(name="wrapper", body=object())
    with pytest.raises(FactoryPanic) as raised:
        replace(impl, decorators=(decorator,)).callsite((TermValue(3),), (), wraps_call)
    assert "decorator factory:wraps" in raised.value.info.owner


def test_decorator_result_projects_static_typing_cast_callable() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    from typing import cast\n"
        "    def decorate(func):\n"
        "        def wrapper(value):\n"
        "            return func(value) + 1\n"
        "        return cast(object, wrapper)\n"
        "    @decorate\n"
        "    def doubled(value):\n"
        "        return value * 2\n"
        "    return doubled(3)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="decorator typing.cast substitution", project_callsite=False
    ) == TermValue(7)


def _function_callable_with_body(name: str = "inner") -> FunctionCallable:
    """Minimal nested def whose statement reduction yields a FunctionCallable."""
    universe = _root_universe(
        "def outer():\n"
        f"    def {name}(value):\n"
        "        return value\n"
        f"    return {name}(3)\n"
    )
    defined = universe.record.statements[0]
    assert isinstance(defined, FunctionCallable)
    assert defined.body is not None
    return defined


def test_array_function_dispatch_preserves_implementation_callsite() -> None:
    """#5152: body-less NEP-18 decorator factories must not abort enumerate.

    The live numpy hole is ``@array_function_dispatch(...)`` via functools.partial,
    so the decorator CallSiteValue arrives with body=None. Default-dispatch public
    API body is the implementation — construct that, never soft-continue.
    """
    from dataclasses import replace

    from sugar_lift_py_tests.ir import ctor

    site = SourceFragment.from_source("rot90(m)\n", "call.py").statements()[0]
    impl = _function_callable_with_body("rot90")
    decorator = CallSiteValue(
        target_name="array_function_dispatch",
        arg_values=(FunctionCallable(name="_rot90_dispatcher", parameters=("m",)),),
        parameters=(),
        term=ctor(
            "call:array_function_dispatch",
            [],
            symbol_kind="coordinate",
        ),
        body=None,
        site=site,
    )
    decorated = replace(impl, decorators=(decorator,))
    applied = decorated._apply_decorators(site)
    assert isinstance(applied, FunctionCallable)
    assert applied.decorators == ()
    assert applied.body is not None
    assert applied.name == "rot90"

    callsite = complete_value(
        decorated.callsite((TermValue(1),), (), site),
        owner="array_function_dispatch enumerate pin",
    )
    assert isinstance(callsite, CallSiteValue)
    assert callsite.body is not None
    assert callsite.target_name == "rot90"
    ctx = FactoryBuildContext(filename="call.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="array_function_dispatch floor", project_callsite=False
    ) == TermValue(1)


def test_array_function_from_c_func_and_dispatcher_preserves_implementation() -> None:
    from dataclasses import replace

    from sugar_lift_py_tests.ir import ctor

    site = SourceFragment.from_source("vdot(a)\n", "call.py").statements()[0]
    impl = _function_callable_with_body("vdot")
    decorator = CallSiteValue(
        target_name="array_function_from_c_func_and_dispatcher",
        arg_values=(),
        parameters=(),
        term=ctor(
            "call:array_function_from_c_func_and_dispatcher",
            [],
            symbol_kind="coordinate",
        ),
        body=None,
        site=site,
    )
    decorated = replace(impl, decorators=(decorator,))
    applied = decorated._apply_decorators(site)
    assert applied.decorators == ()
    assert applied.body is not None


def test_unknown_decorator_factory_missing_body_names_owner() -> None:
    """Residual body-less decorator factories stay loud with the factory name."""
    from dataclasses import replace

    from sugar_lift_py_tests.ir import ctor

    site = SourceFragment.from_source("f()\n", "call.py").statements()[0]
    impl = _function_callable_with_body("inner")
    unknown = CallSiteValue(
        target_name="mystery_wrap",
        arg_values=(),
        parameters=(),
        term=ctor("call:mystery_wrap", [], symbol_kind="coordinate"),
        body=None,
        site=site,
    )
    decorated = replace(impl, decorators=(unknown,))
    with pytest.raises(FactoryPanic) as raised:
        decorated.callsite((TermValue(1),), (), site)
    info = raised.value.info
    assert info.owner == "FunctionCallable decorator factory:mystery_wrap"
    assert "mystery_wrap" in str(info.observed)
    assert "never soft-continue" in info.fix


def test_incomplete_decorator_result_is_a_named_factory_panic() -> None:
    """A typed-red decorator body must not escape as a bare RuntimeError."""
    from dataclasses import replace

    from sugar_lift_py_tests.effect import (
        ConditionalExpressionRuntimeEffect,
        runtime_effect_evidence_from_terms,
    )
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_lift_py_tests.sugar_body import SugarBody

    site = SourceFragment.from_source("decorated(1)\n", "decorator.py").statements()[0]
    operand = make_var("runtime_name")
    effect = ConditionalExpressionRuntimeEffect(
        "decorator result depends on a runtime conditional",
        **runtime_effect_evidence_from_terms(
            ctor("py.ifexp.select", [operand]),
            operand,
            site,
        ),
    )

    class IncompleteDecoratorResult:
        def desugar(self, ctx=None):
            del ctx
            return Incomplete(effect)

    decorator = FunctionCallable(
        name="decorate",
        parameters=("func",),
        parameter_kinds=("positional",),
        body=SugarBody(
            sugar=IncompleteDecoratorResult(),
            role=SugarRole.TERM,
        ),
    )
    decorated = replace(
        _function_callable_with_body("decorated"), decorators=(decorator,)
    )

    with pytest.raises(FactoryPanic) as raised:
        decorated.callsite((TermValue(1),), (), site)

    info = raised.value.info
    assert info.owner == "FunctionCallable decorator result:decorate"
    assert info.observed == "ConditionalExpressionRuntimeEffect"
    assert info.requested == "completed decorator result substitution"


def test_callable_merges_explicit_keyword_into_guarded_static_mapping() -> None:
    site = SourceFragment.from_source(
        "inner(obj='left', **options)\n", "nested.py"
    ).statements()[0]
    guard = atomic("mapping-choice", [])
    expansion = GuardedValue(
        guard,
        DictValue(((StringValue("check"), TermValue(1)),)),
        DictValue(()),
    )
    callable_value = FunctionCallable(
        name="inner",
        parameters=("left", "right", "options"),
        parameter_kinds=("positional", "positional", "var-keyword"),
        body=object(),
    )

    outcome = callable_value.callsite(
        (TermValue(1), TermValue(2), StringValue("left"), expansion),
        ("obj", "**"),
        site,
    )

    callsite = complete_value(outcome, owner="guarded kwargs substitution")
    assert isinstance(callsite, CallSiteValue)
    options = callsite.arg_values[-1]
    assert isinstance(options, GuardedValue)
    assert options.when_true == DictValue(
        (
            (StringValue("obj"), StringValue("left")),
            (StringValue("check"), TermValue(1)),
        )
    )
    assert options.when_false == DictValue(((StringValue("obj"), StringValue("left")),))


def test_unconstructed_decorator_stays_loud() -> None:
    site = SourceFragment.from_source("inner(1)\n", "nested.py").statements()[0]
    callable_value = FunctionCallable(
        name="inner",
        parameters=("value",),
        parameter_kinds=("positional",),
        decorators=(TermValue(0),),
        body=object(),
    )

    with pytest.raises(FactoryPanic) as raised:
        callable_value.callsite((TermValue(1),), (), site)

    assert raised.value.info.owner == "FunctionCallable"
    assert raised.value.info.observed == "TermValue"
    assert raised.value.info.requested == "decorator callable substitution"


def test_nested_callable_captures_lexical_bindings_and_overlays_actuals() -> None:
    universe = _root_universe(
        "def outer(x):\n"
        "    offset = 4\n"
        "    def inner(y):\n"
        "        adjusted = y + offset\n"
        "        return adjusted\n"
        "    return inner(x)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    dug = callsite.force_floor(
        ctx, owner="nested closure regression", project_callsite=False
    )
    assert dug == TermValue(9)


def test_nested_callable_constructs_its_own_deferred_lexical_binding() -> None:
    universe = _root_universe(
        "def outer(values):\n"
        "    def inner(items):\n"
        "        return tuple(map(inner, items))\n"
        "    return inner(values)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    from sugar_lift_py_tests.floor.call_site_value import (
        _ctx_with_curried_args,
        _reduce_callsite_body,
    )

    assert isinstance(
        complete_value(
            _reduce_callsite_body(
                callsite.body,
                _ctx_with_curried_args(ctx, callsite.parameters, callsite.arg_values),
                blame=callsite.target_name,
            ),
            owner="nested callable self binding",
        ),
        CallSiteValue,
    )


def test_nested_callable_does_not_bind_a_different_missing_global() -> None:
    universe = _root_universe(
        "def outer(values):\n"
        "    def inner(items):\n"
        "        return tuple(map(never_defined, items))\n"
        "    return inner(values)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    from sugar_lift_py_tests.floor.call_site_value import (
        _ctx_with_curried_args,
        _reduce_callsite_body,
    )

    with pytest.raises(FactoryPanic) as raised:
        _reduce_callsite_body(
            callsite.body,
            _ctx_with_curried_args(ctx, callsite.parameters, callsite.arg_values),
            blame=callsite.target_name,
        )

    assert raised.value.info.owner == "TemporalContext"
    assert raised.value.info.observed == "never_defined"


def test_nested_callable_binds_an_omitted_trailing_default_without_rekeying_callsite() -> (
    None
):
    universe = _root_universe(
        "def outer():\n"
        "    def inner(y, increment=4):\n"
        "        return y + increment\n"
        "    return inner(5)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("y", "increment")
    assert callsite.arg_values == (TermValue(5), TermValue(4))
    # Identity belongs to the consumer spelling, not to the expanded binding.
    assert callsite.term == ctor("call:inner", [num(5)])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="nested default regression", project_callsite=False
    ) == TermValue(9)


def test_nested_callable_binds_multiple_omitted_trailing_defaults_in_formal_order() -> (
    None
):
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, first=4, second=6):\n"
        "        return required + first + second\n"
        "    return inner(5)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("required", "first", "second")
    assert callsite.arg_values == (TermValue(5), TermValue(4), TermValue(6))
    assert callsite.term == ctor("call:inner", [num(5)])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="multiple default alignment", project_callsite=False
    ) == TermValue(15)


def test_nested_callable_supplied_positional_overrides_only_its_aligned_default() -> (
    None
):
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, first=4, second=6):\n"
        "        return required + first + second\n"
        "    return inner(5, 10)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.arg_values == (TermValue(5), TermValue(10), TermValue(6))
    assert callsite.term == ctor("call:inner", [num(5), num(10)])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="supplied default override", project_callsite=False
    ) == TermValue(21)


def test_nested_callable_default_is_assigned_once_at_its_temporal_coordinate() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    x = 5\n"
        "    def inner(value=x):\n"
        "        return value\n"
        "    x = 9\n"
        "    return inner()\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.arg_values == (TermValue(5),)
    assert callsite.term == ctor("call:inner", [])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="nested default assignment", project_callsite=False
    ) == TermValue(5)


def test_nested_callable_missing_required_positional_is_static_type_error() -> None:
    universe = _root_universe(
        "def outer(x):\n"
        "    def inner(required, optional=4):\n"
        "        return required + optional\n"
        "    return inner()\n"
    )

    exit_value = universe.record.statements[-1]
    assert isinstance(exit_value, RaiseValue)
    assert exit_value.effect.exception_name == "TypeError"
    assert exit_value.exception is not None
    assert exit_value.exception.exception_name == "TypeError"


def test_nested_callable_extra_positional_is_static_type_error() -> None:
    universe = _root_universe(
        "def outer(x):\n"
        "    def inner(required, optional=4):\n"
        "        return required + optional\n"
        "    return inner(x, 6, 7)\n"
    )

    exit_value = universe.record.statements[-1]
    assert isinstance(exit_value, RaiseValue)
    assert exit_value.effect.exception_name == "TypeError"
    assert exit_value.exception is not None
    assert exit_value.exception.exception_name == "TypeError"


def test_nested_callable_binds_empty_variadic_parameters_without_rekeying_callsite() -> (
    None
):
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, /, *extras, **options):\n"
        "        return extras\n"
        "    return inner(5)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("required", "extras", "options")
    assert callsite.arg_values == (TermValue(5), TupleValue(()), DictValue(()))
    assert callsite.term == ctor("call:inner", [num(5)])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="empty variadic binding", project_callsite=False
    ) == TupleValue(())


def test_nested_callable_collects_surplus_positionals_in_source_order_without_rekeying_callsite() -> (
    None
):
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, /, *extras, **options):\n"
        "        return extras\n"
        "    return inner(5, 6, 7, 8)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("required", "extras", "options")
    assert callsite.arg_values == (
        TermValue(5),
        TupleValue((TermValue(6), TermValue(7), TermValue(8))),
        DictValue(()),
    )
    assert callsite.term == ctor("call:inner", [num(5), num(6), num(7), num(8)])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="surplus positional binding", project_callsite=False
    ) == TupleValue((TermValue(6), TermValue(7), TermValue(8)))


def test_nested_callable_binds_single_keyword_expansion_to_var_keyword() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(**options):\n"
        '        return options["value"]\n'
        '    return inner(**{"value": 5})\n'
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("options",)
    assert len(callsite.arg_values) == 1
    assert isinstance(callsite.arg_values[0], DictValue)
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="keyword expansion binding", project_callsite=False
    ) == TermValue(5)


def test_nested_callable_binds_default_before_single_keyword_expansion() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, optional=4, **options):\n"
        '        return optional + options["value"]\n'
        '    return inner(1, **{"value": 5})\n'
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.arg_values == (
        TermValue(1),
        TermValue(4),
        DictValue(((StringValue("value"), TermValue(5)),)),
    )
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="default plus keyword expansion", project_callsite=False
    ) == TermValue(9)


def test_nested_callable_merges_explicit_keyword_with_constructed_expansion() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required=4, **options):\n"
        '        return required + options["left"] + options["right"]\n'
        '    return inner(left=1, **{"right": 2})\n'
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.arg_values == (
        TermValue(4),
        DictValue(
            (
                (StringValue("left"), TermValue(1)),
                (StringValue("right"), TermValue(2)),
            )
        ),
    )
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="merged keyword expansion", project_callsite=False
    ) == TermValue(7)


def test_nested_callable_opaque_expansion_has_authenticated_binding_effect() -> None:
    site = SourceFragment.from_source(
        "inner(flag=1, **options)\n", "nested.py"
    ).statements()[0]
    callable_value = FunctionCallable(
        "inner",
        parameters=("required", "kwargs"),
        parameter_kinds=("positional", "var-keyword"),
        positional_defaults=(TermValue(4),),
        body=object(),
    )
    expansion = SymbolicValue(make_var("options"))

    outcome = callable_value.callsite(
        (TermValue(1), expansion),
        ("flag", "**"),
        site,
    )

    assert isinstance(outcome, Incomplete)
    assert type(outcome.effect).__name__ == "CallableArgumentBindingRuntimeEffect"
    assert outcome.effect.runtime_operand.term == expansion.term
    assert outcome.effect.witness.operand == expansion.term


def test_runtime_dict_key_expansion_has_authenticated_binding_effect() -> None:
    site = SourceFragment.from_source("inner(**options)\n", "nested.py").statements()[0]
    callable_value = FunctionCallable(
        "inner",
        parameters=("value",),
        parameter_kinds=("positional",),
        body=object(),
    )
    expansion = DictValue(((SymbolicValue(make_var("runtime_key")), TermValue(5)),))

    outcome = callable_value.callsite((expansion,), ("**",), site)

    assert isinstance(outcome, Incomplete)
    assert type(outcome.effect).__name__ == "CallableArgumentBindingRuntimeEffect"
    assert outcome.effect.runtime_operand.term == expansion.to_term(owner="test")
    assert outcome.effect.witness.operand == expansion.to_term(owner="test")


def test_ground_keyword_expansion_cannot_mint_argument_binding_effect() -> None:
    from sugar_lift_py_tests.effect import runtime_callable_argument_binding
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    site = SourceFragment.from_source("f(**{})\n", "ground.py").statements()[0]

    with pytest.raises(FactoryPanic, match="owner=RuntimeEffect"):
        runtime_callable_argument_binding(DictValue(()), site)


def test_nested_callable_binds_bodyless_callsite_keyword_expansion() -> None:
    universe = _root_universe(
        "def outer(self):\n"
        "    def inner(result, func, **options):\n"
        "        return options\n"
        "    return inner(1, 2, **self.options)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("result", "func", "options")
    assert callsite.arg_values[:2] == (TermValue(1), TermValue(2))
    expansion = callsite.arg_values[2]
    assert isinstance(expansion, CallSiteValue)
    assert expansion.target_name == "options"
    assert expansion.body is None


def test_nested_callable_body_bearing_callsite_expansion_stays_loud() -> None:
    site = SourceFragment.from_source(
        "inner(1, 2, **options)\n", "nested.py"
    ).statements()[0]
    expansion = CallSiteValue(
        target_name="options",
        arg_values=(),
        parameters=(),
        term=ctor("call:options", []),
        body=object(),
        site=site,
    )
    callable_value = FunctionCallable(
        name="inner",
        parameters=("result", "func", "options"),
        parameter_kinds=("positional", "positional", "var-keyword"),
        body=object(),
    )

    with pytest.raises(FactoryPanic, match="owner=FunctionCallable"):
        callable_value.callsite(
            (TermValue(1), TermValue(2), expansion),
            ("**",),
            site,
        )


def test_nested_callable_digs_body_bearing_keyword_expansion() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def options():\n"
        "        return {'x': 1, 'y': 2}\n"
        "    def inner(**kwargs):\n"
        "        return kwargs['x'] + kwargs['y']\n"
        "    return inner(**options())\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("kwargs",)
    assert callsite.arg_values == (
        DictValue(
            (
                (StringValue("x"), TermValue(1)),
                (StringValue("y"), TermValue(2)),
            )
        ),
    )
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="diggable keyword expansion", project_callsite=False
    ) == TermValue(3)


def test_nested_callable_merges_multiple_constructed_keyword_expansions() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(**kwargs):\n"
        "        return kwargs['x'] + kwargs['y']\n"
        "    return inner(**{'x': 1}, **{'y': 2})\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.arg_values == (
        DictValue(
            (
                (StringValue("x"), TermValue(1)),
                (StringValue("y"), TermValue(2)),
            )
        ),
    )
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="multi keyword expansion", project_callsite=False
    ) == TermValue(3)


def test_nested_callable_keyword_expansion_key_collision_is_static_type_error() -> None:
    site = SourceFragment.from_source(
        "inner(flag=1, **options)\n", "nested.py"
    ).statements()[0]
    callable_value = FunctionCallable(
        name="inner",
        parameters=("kwargs",),
        parameter_kinds=("var-keyword",),
        body=object(),
    )
    expansion = DictValue(((StringValue("flag"), TermValue(2)),))

    outcome = callable_value.callsite(
        (TermValue(1), expansion),
        ("flag", "**"),
        site,
    )

    value = complete_value(outcome, owner="keyword expansion collision")
    assert isinstance(value, RaiseValue)
    assert value.effect.exception_name == "TypeError"


def test_nested_callable_expands_constructed_starred_args_with_keywords() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(*args, **options):\n"
        "        return args\n"
        "    return inner(*(1, 2), flag=3)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("args", "options")
    assert callsite.arg_values == (
        TupleValue((TermValue(1), TermValue(2))),
        DictValue(((StringValue("flag"), TermValue(3)),)),
    )


def test_nested_callable_ground_non_mapping_keyword_expansion_stays_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _root_universe(
            "def outer():\n"
            "    def inner(**options):\n"
            "        return options\n"
            "    return inner(**5)\n"
        )

    assert raised.value.info.owner == "FunctionCallable"
    assert raised.value.info.requested == "bind call arguments to a function signature"


def test_nested_callable_constructs_static_unexpected_keyword_type_error() -> None:
    site = SourceFragment.from_source("inner(1, extra=2)\n", "nested.py").statements()[
        0
    ]
    callable_value = FunctionCallable(
        name="inner",
        parameters=("value",),
        parameter_kinds=("positional",),
        body=object(),
    )

    outcome = callable_value.callsite(
        (TermValue(1), TermValue(2)),
        ("extra",),
        site,
    )

    value = complete_value(outcome, owner="unexpected keyword regression")
    assert isinstance(value, RaiseValue)
    assert value.effect.exception_name == "TypeError"
    assert value.exception is not None
    assert value.exception.exception_name == "TypeError"


def test_nested_callable_valid_keyword_still_constructs_callsite() -> None:
    site = SourceFragment.from_source("inner(value=1)\n", "nested.py").statements()[0]
    callable_value = FunctionCallable(
        name="inner",
        parameters=("value",),
        parameter_kinds=("positional",),
        body=object(),
    )

    value = complete_value(
        callable_value.callsite((TermValue(1),), ("value",), site),
        owner="valid keyword discrimination",
    )

    assert isinstance(value, CallSiteValue)
    assert value.arg_values == (TermValue(1),)


def test_nested_callable_opaque_expansion_to_fixed_signature_is_runtime() -> None:
    site = SourceFragment.from_source("inner(**options)\n", "nested.py").statements()[0]
    callable_value = FunctionCallable(
        name="inner",
        parameters=("value",),
        parameter_kinds=("positional",),
        body=object(),
    )
    expansion = SymbolicValue(make_var("options"))

    outcome = callable_value.callsite((expansion,), ("**",), site)

    assert isinstance(outcome, Incomplete)
    assert type(outcome.effect).__name__ == "CallableArgumentBindingRuntimeEffect"
    assert outcome.effect.witness.operand == expansion.term


def test_keyword_expansion_witness_truthful_sat_and_lying_unsat(tmp_path) -> None:
    witness = next(
        witness
        for witness in StatementFunctionDefSugar.witnesses()
        if witness.name == "statement_function_def_keyword_expansion_return"
    )

    report = evaluate_seed_witnesses((witness,), tmp_path)

    assert report.is_zero


def test_default_keyword_expansion_witness_truthful_sat_and_lying_unsat(
    tmp_path,
) -> None:
    witness = next(
        witness
        for witness in StatementFunctionDefSugar.witnesses()
        if witness.name == "statement_function_def_default_keyword_expansion_return"
    )

    report = evaluate_seed_witnesses((witness,), tmp_path)

    assert report.is_zero


def test_diggable_keyword_expansion_witness_truthful_sat_and_lying_unsat(
    tmp_path,
) -> None:
    witness = next(
        witness
        for witness in StatementFunctionDefSugar.witnesses()
        if witness.name == "statement_function_def_diggable_keyword_expansion_return"
    )

    report = evaluate_seed_witnesses((witness,), tmp_path)

    assert report.is_zero


def test_multi_keyword_expansion_witness_truthful_sat_and_lying_unsat(tmp_path) -> None:
    witness = next(
        witness
        for witness in StatementFunctionDefSugar.witnesses()
        if witness.name == "statement_function_def_multi_keyword_expansion_return"
    )

    report = evaluate_seed_witnesses((witness,), tmp_path)

    assert report.is_zero


def test_decorated_callable_substitution_witness_truthful_sat_and_lying_unsat(
    tmp_path,
) -> None:
    witness = next(
        witness
        for witness in StatementFunctionDefSugar.witnesses()
        if witness.name == "statement_function_def_decorated_callable_substitution"
    )

    report = evaluate_seed_witnesses((witness,), tmp_path)

    assert report.is_zero


def test_callable_self_binding_witness_truthful_sat_and_lying_unsat(tmp_path) -> None:
    witness = next(
        witness
        for witness in StatementFunctionDefSugar.witnesses()
        if witness.name == "statement_function_def_self_binding_return"
    )

    report = evaluate_seed_witnesses((witness,), tmp_path)

    assert report.is_zero


def test_unexpected_keyword_type_error_witness_truthful_sat_and_lying_unsat(
    tmp_path,
) -> None:
    witness = next(
        witness
        for witness in StatementFunctionDefSugar.witnesses()
        if witness.name == "statement_function_def_unexpected_keyword_type_error"
    )

    report = evaluate_seed_witnesses((witness,), tmp_path)

    assert report.is_zero


def test_constructed_starred_keyword_witness_truthful_sat_and_lying_unsat(
    tmp_path,
) -> None:
    witness = next(
        witness
        for witness in KeywordCallSugar.witnesses()
        if witness.name == "keyword_call_constructed_starred_return"
    )

    report = evaluate_seed_witnesses((witness,), tmp_path)

    assert report.is_zero


def test_nested_callable_aligns_positional_default_before_collecting_surplus() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, optional=4, *extras, **options):\n"
        "        return extras\n"
        "    return inner(5, 10, 11, 12)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("required", "optional", "extras", "options")
    assert callsite.arg_values == (
        TermValue(5),
        TermValue(10),
        TupleValue((TermValue(11), TermValue(12))),
        DictValue(()),
    )
    assert callsite.term == ctor("call:inner", [num(5), num(10), num(11), num(12)])


def test_nested_callable_omitted_positional_default_precedes_empty_variadics() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, optional=4, *extras, **options):\n"
        "        return optional\n"
        "    return inner(5)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.arg_values == (
        TermValue(5),
        TermValue(4),
        TupleValue(()),
        DictValue(()),
    )
    assert callsite.term == ctor("call:inner", [num(5)])


def test_nested_callable_exact_fixed_positional_control_stays_unchanged() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required):\n"
        "        return required\n"
        "    return inner(5)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("required",)
    assert callsite.arg_values == (TermValue(5),)
    assert callsite.term == ctor("call:inner", [num(5)])


def test_nested_callable_binds_one_omitted_keyword_only_default() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, *, increment=4):\n"
        "        return required + increment\n"
        "    return inner(5)\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("required", "increment")
    assert callsite.arg_values == (TermValue(5), TermValue(4))
    assert callsite.term == ctor("call:inner", [num(5)])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="keyword-only default omission", project_callsite=False
    ) == TermValue(9)


def test_nested_callable_binds_multiple_keyword_only_defaults_in_exact_order() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(*, first=4, second=6):\n"
        "        return first * 10 + second\n"
        "    return inner()\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("first", "second")
    assert callsite.arg_values == (TermValue(4), TermValue(6))
    assert callsite.term == ctor("call:inner", [])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="keyword-only default order", project_callsite=False
    ) == TermValue(46)


def test_nested_callable_separates_positional_and_keyword_only_defaults() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(positional=3, *, keyword_only=7):\n"
        "        return positional * 10 + keyword_only\n"
        "    return inner()\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.parameters == ("positional", "keyword_only")
    assert callsite.arg_values == (TermValue(3), TermValue(7))
    assert callsite.term == ctor("call:inner", [])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="separate default alignment", project_callsite=False
    ) == TermValue(37)


def test_nested_callable_keyword_only_default_is_captured_at_definition_time() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    captured = 5\n"
        "    def inner(*, value=captured):\n"
        "        return value\n"
        "    captured = 9\n"
        "    return inner()\n"
    )

    callsite = universe.record.statements[-1].value
    assert isinstance(callsite, CallSiteValue)
    assert callsite.arg_values == (TermValue(5),)
    assert callsite.term == ctor("call:inner", [])
    ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    assert callsite.force_floor(
        ctx, owner="keyword-only default capture", project_callsite=False
    ) == TermValue(5)


def test_nested_callable_missing_required_keyword_only_is_static_type_error() -> None:
    universe = _root_universe(
        "def outer():\n"
        "    def inner(*, required):\n"
        "        return required\n"
        "    return inner()\n"
    )

    exit_value = universe.record.statements[-1]
    assert isinstance(exit_value, RaiseValue)
    assert exit_value.effect.exception_name == "TypeError"


def test_nested_callable_keyword_only_boundary_is_not_filled_by_surplus_positionals() -> (
    None
):
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, /, *extras, flag, **options):\n"
        "        return extras\n"
        "    return inner(5, 6, 7)\n"
    )

    exit_value = universe.record.statements[-1]
    assert isinstance(exit_value, RaiseValue)
    assert exit_value.effect.exception_name == "TypeError"


def test_nested_callable_empty_variadics_do_not_hide_missing_required_positional() -> (
    None
):
    universe = _root_universe(
        "def outer():\n"
        "    def inner(required, *extras, **options):\n"
        "        return required\n"
        "    return inner()\n"
    )

    exit_value = universe.record.statements[-1]
    assert isinstance(exit_value, RaiseValue)
    assert exit_value.effect.exception_name == "TypeError"


def test_decorated_statement_def_stays_loud() -> None:
    node = (
        ast.parse(
            "def outer(x):\n"
            "    @decorate\n"
            "    def inner(y):\n"
            "        return y\n"
            "    return inner(x)\n"
        )
        .body[0]
        .body[0]
    )
    catalog = default_catalog()
    ctx = FactoryBuildContext(filename="decorated.py", catalog=catalog)

    result = build_node(
        node,
        filename="decorated.py",
        role=SugarRole.STATEMENT,
        ctx=ctx,
    )
    with pytest.raises(FactoryPanic) as raised:
        result.sugar.desugar(ctx)

    assert raised.value.info.observed == "decorate"
    assert raised.value.info.requested == "value"
    assert "bind `decorate`" in raised.value.info.fix


def test_definition_and_statement_roles_have_distinct_registered_owners() -> None:
    claims = {claim.name: claim for claim in default_catalog().claims}

    assert claims["FunctionDefSugar"].role.value == "definition"
    assert claims["TestFunctionDefSugar"].role.value == "definition"
    assert claims["StatementFunctionDefSugar"].role is SugarRole.STATEMENT
