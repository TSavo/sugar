# SPDX-License-Identifier: MIT OR Apache-2.0
"""Install-source body dig: CallSugar attaches body when resolve succeeds."""

from __future__ import annotations
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditStatus

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.sugar.install_source_dig import (
    SequentialDigBody,
    resolve_install_source_funcdef,
    module_sibling_function_nodes,
)


def test_same_module_call_attaches_body() -> None:
    """def B; A calls B — CallSiteValue.body is non-None after lift."""
    src = (
        "def B(w):\n"
        "    return w\n"
        "def A(z):\n"
        "    return B(z)\n"
        "def test_a():\n"
        "    assert A(5) == 5\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    # Prove dig path: force_floor on A should use body; ir has assertion
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] >= 1, ax
    # factory walk / ir should exist for A or test
    assert (rpc.get("ir") or []) or ax["lifted_cited"]


def test_resolve_install_source_base64() -> None:
    resolved = resolve_install_source_funcdef("base64.urlsafe_b64encode")
    assert resolved is not None
    assert resolved.function_name() == "urlsafe_b64encode"
    assert getattr(resolved.node, "_sugar_file", None)


def test_module_siblings_base64() -> None:
    siblings = module_sibling_function_nodes("base64")
    assert "urlsafe_b64encode" in siblings or "base64.urlsafe_b64encode" in siblings


def test_install_source_reads_python_definitions_without_executing_skip(
    tmp_path, monkeypatch
) -> None:
    module = tmp_path / "pandas_optional_dependency_repro.py"
    module.write_text(
        "import pytest\n"
        "tables = pytest.importorskip('sugar_missing_tables_for_test')\n"
        "def helper():\n"
        "    return tables\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    siblings = module_sibling_function_nodes("pandas_optional_dependency_repro")

    assert "helper" in siblings
    assert "pandas_optional_dependency_repro" not in __import__("sys").modules


def test_install_source_missing_module_has_no_invented_definitions() -> None:
    assert module_sibling_function_nodes("sugar_module_that_does_not_exist") == {}


def test_from_import_pure_function_lifts() -> None:
    """from itsdangerous.encoding import int_to_bytes — body dig or coordinate."""
    src = (
        "from itsdangerous.encoding import int_to_bytes, bytes_to_int\n"
        "def test_e():\n"
        "    assert bytes_to_int(int_to_bytes(192)) == 192\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] == 1, ax


def test_nested_external_bridge_default_false() -> None:
    from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
    from sugar_lift_py_tests.factory.build import default_catalog

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    assert ctx.nested_external_bridge is False


class _NoReturnOutcome:
    def extend_scope(self, ctx):
        return ctx

    def contribution(self):
        return ()


class _NoReturnStatement:
    def __init__(self) -> None:
        from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditRow

        self.audit_row = FactoryAuditRow(
            role="statement",
            status=FactoryAuditStatus.SELECTED,
            observed="If",
            blame="numpy/_core/repro.py:17:4",
            selected="IfSugar",
            candidates=["IfSugar"],
            message="selected IfSugar",
        )

    def reduce(self, ctx):
        del ctx
        return _NoReturnOutcome()


def test_sequential_dig_stops_at_first_unguarded_return() -> None:
    """#4387: dig must not walk past an early return to a later fall-through.

    ``if cond: return 7`` / ``return 0`` with a taken then-arm previously kept
    ``last_return = 0``, fabricating Derived EUF ``call:A=0`` that dual-refuted
    truthful ``assert A(1) == 7``.
    """
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.outcome import Complete

    class _ReturnStatement:
        def __init__(self, value: int) -> None:
            self._value = value

        def reduce(self, ctx):
            del ctx
            return Complete(ReturnValue(TermValue(self._value)))

    outcome = SequentialDigBody((_ReturnStatement(7), _ReturnStatement(0))).desugar()

    assert isinstance(outcome, Complete)
    assert outcome.value == TermValue(7)


def test_sequential_dig_refuses_guarded_multi_exit_as_single_literal() -> None:
    """Ground guard descriptions cannot mint runtime-dependence evidence."""
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.ir import atomic, num
    from sugar_lift_py_tests.outcome import Complete

    guard = atomic("py.eq", [num(1), num(1)])

    class _GuardedReturnStatement:
        def reduce(self, ctx):
            del ctx
            return Complete(GuardedReturn(guards=(guard,), value=TermValue(7)))

    class _FallthroughReturn:
        def reduce(self, ctx):
            del ctx
            return Complete(
                GuardedReturn(
                    guards=(atomic("py.eq", [num(0), num(1)]),),
                    value=TermValue(0),
                )
            )

    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    fn_site = SourceFragment.from_source(
        "def f(x):\n    if x:\n        return 1\n    return 0\n",
        "numpy/_core/repro.py",
    ).statements()[0]
    with pytest.raises(FactoryPanic):
        SequentialDigBody(
            (_GuardedReturnStatement(), _FallthroughReturn()),
            fn_site=fn_site,
        ).desugar()


def test_sequential_dig_constructs_guarded_early_return_with_fallback() -> None:
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.ir import atomic, make_var, num
    from sugar_lift_py_tests.outcome import Complete

    guard = atomic("py.eq", [make_var("z"), num(1)])

    class _GuardedReturnStatement:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return Complete(GuardedReturn(guards=(guard,), value=TermValue(7)))

    class _FallbackReturnStatement:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return Complete(ReturnValue(TermValue(0)))

    fn_site = SourceFragment.from_source(
        "def f(z):\n    if z == 1:\n        return 7\n    return 0\n",
        "numpy/f2py/symbolic.py",
    ).statements()[0]
    outcome = SequentialDigBody(
        (_GuardedReturnStatement(), _FallbackReturnStatement()),
        fn_site=fn_site,
    ).desugar()

    assert isinstance(outcome, Complete)
    assert outcome.value == GuardedValue(guard, TermValue(7), TermValue(0))


def test_sequential_dig_constructs_exhaustive_nested_guarded_returns() -> None:
    from sugar_lift_py_tests.floor import BlockValue
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.ir import make_var, not_
    from sugar_lift_py_tests.outcome import Complete

    outer = make_var("is_frame")
    inner = make_var("is_empty")

    class _ExhaustiveNestedReturnStatement:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return Complete(
                BlockValue(
                    (
                        GuardedReturn((outer, inner), TermValue(1)),
                        GuardedReturn((outer, not_(inner)), TermValue(2)),
                        GuardedReturn((not_(outer),), TermValue(3)),
                    ),
                    can_fall_through=False,
                )
            )

    outcome = SequentialDigBody((_ExhaustiveNestedReturnStatement(),)).desugar()

    assert isinstance(outcome, Complete)
    assert outcome.value == GuardedValue(
        outer,
        GuardedValue(inner, TermValue(1), TermValue(2)),
        TermValue(3),
    )


def test_sequential_dig_constructs_guarded_raise_with_fallback() -> None:
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.floor import BlockValue, GuardedRaise
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.ir import atomic, make_var, num
    from sugar_lift_py_tests.outcome import Complete

    guard = atomic("py.eq", [make_var("z"), num(0)])
    raised = RaiseEffect(
        exception_name="ValueError",
        blame="vendor/pkg/repro.py:2:8",
        source_sha256="0" * 64,
    )

    class _GuardedRaiseStatement:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return Complete(BlockValue((GuardedRaise(guards=(guard,), effect=raised),)))

    class _FallbackReturnStatement:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return Complete(ReturnValue(TermValue(7)))

    outcome = SequentialDigBody(
        (_GuardedRaiseStatement(), _FallbackReturnStatement())
    ).desugar()

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, GuardedValue)
    assert outcome.value.guard == guard
    assert "py.exceptional_exit" in repr(outcome.value.when_true.to_term(owner="test"))
    assert outcome.value.when_false == TermValue(7)


def test_sequential_dig_guarded_raise_with_state_stays_loud() -> None:
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.floor import BlockValue, GuardedRaise, ScopeRebind
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.ir import atomic, make_var, num
    from sugar_lift_py_tests.outcome import Complete

    guard = atomic("py.eq", [make_var("z"), num(0)])

    class _MixedStatement:
        audit_row = None

        def reduce(self, ctx):
            del ctx

            class _MixedOutcome:
                def contribution(self):
                    return (
                        GuardedRaise(
                            guards=(guard,),
                            effect=RaiseEffect(
                                "ValueError",
                                "vendor/pkg/repro.py:2:8",
                                "0" * 64,
                            ),
                        ),
                        ScopeRebind("state", TermValue(9)),
                    )

                def extend_scope(self, current):
                    return current

            return _MixedOutcome()

    class _FallbackReturnStatement:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return Complete(ReturnValue(TermValue(7)))

    with pytest.raises(FactoryPanic):
        SequentialDigBody((_MixedStatement(), _FallbackReturnStatement())).desugar()


def test_sequential_dig_consumes_guarded_faces_join_before_fallback_return() -> None:
    from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.factory.build import default_catalog
    from sugar_lift_py_tests.floor import (
        GuardedFaces,
        GuardedRaise,
        GuardedScopeRebind,
    )
    from sugar_lift_py_tests.floor.exceptional_exit_value import ExceptionalExitValue
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.ir import make_var, not_
    from sugar_lift_py_tests.outcome import Complete

    invalid = make_var("invalid_dtype")
    selected = GuardedValue(
        make_var("use_values"),
        TermValue("from-values"),
        TermValue("from-categories"),
    )
    raised = RaiseEffect(
        exception_name="ValueError",
        blame="pandas/core/dtypes/dtypes.py:338:16",
        source_sha256="0" * 64,
    )

    class _GuardedFacesStatement:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return Complete(
                GuardedFaces(
                    guard=invalid,
                    entries=(
                        GuardedRaise((invalid,), raised),
                        GuardedScopeRebind(
                            (not_(invalid),),
                            "ordered",
                            TermValue(False),
                        ),
                    ),
                    then_exits=True,
                    else_exits=False,
                    joined_bindings=(("dtype", selected),),
                    can_fall_through=True,
                    continuation_guard=not_(invalid),
                )
            )

    class _ReturnJoinedDtype:
        audit_row = None

        def reduce(self, ctx):
            return Complete(ReturnValue(ctx.temporal.value_if_bound("dtype")))

    ctx = FactoryBuildContext(filename="repro.py", catalog=default_catalog())
    outcome = SequentialDigBody(
        (_GuardedFacesStatement(), _ReturnJoinedDtype())
    ).desugar(ctx)

    assert isinstance(outcome, Complete)
    assert outcome.value == GuardedValue(
        invalid,
        ExceptionalExitValue(raised),
        selected,
    )


def test_sequential_dig_consumes_joined_faces_with_reduced_support_testimony() -> None:
    from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.factory.build import default_catalog
    from sugar_lift_py_tests.floor import (
        BlockValue,
        GuardedFaces,
        GuardedRaise,
        GuardedScopeRebind,
        ImportAliasValue,
        InvValue,
        ScopeRebind,
    )
    from sugar_lift_py_tests.floor.exceptional_exit_value import ExceptionalExitValue
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.ir import atomic, make_var, not_
    from sugar_lift_py_tests.outcome import Complete

    compression = make_var("compression")
    raised = RaiseEffect(
        exception_name="ValueError",
        blame="pandas/io/common.py:846:20",
        source_sha256="0" * 64,
    )

    class _CompressionFaces:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return Complete(
                GuardedFaces(
                    guard=compression,
                    entries=(
                        GuardedRaise((compression,), raised),
                        GuardedScopeRebind(
                            (not_(compression),),
                            "handle",
                            TermValue("plain"),
                        ),
                        ImportAliasValue("bz2", "bz2"),
                        InvValue(atomic("py.eq", [make_var("mode"), make_var("mode")])),
                    ),
                    then_exits=True,
                    else_exits=False,
                    joined_bindings=(
                        ("handle", TermValue("joined")),
                        ("handles", TermValue("stack")),
                    ),
                    can_fall_through=True,
                    continuation_guard=not_(compression),
                )
            )

    class _ReturnHandle:
        audit_row = None

        def reduce(self, ctx):
            return Complete(ReturnValue(ctx.temporal.value_if_bound("handle")))

    class _GuardedAssertion:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return Complete(
                GuardedFaces(
                    guard=not_(compression),
                    entries=(
                        InvValue(
                            atomic("py.eq", [make_var("handles"), make_var("handles")])
                        ),
                    ),
                    then_exits=False,
                    else_exits=False,
                )
            )

    class _ContinuationState:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return Complete(
                BlockValue(
                    (
                        ScopeRebind("unit", TermValue("us")),
                        GuardedScopeRebind(
                            (not_(compression),),
                            "periods",
                            TermValue(3),
                        ),
                    )
                )
            )

    ctx = FactoryBuildContext(filename="repro.py", catalog=default_catalog())
    outcome = SequentialDigBody(
        (
            _CompressionFaces(),
            _ContinuationState(),
            _GuardedAssertion(),
            _ReturnHandle(),
        )
    ).desugar(ctx)

    assert isinstance(outcome, Complete)
    assert outcome.value == GuardedValue(
        compression,
        ExceptionalExitValue(raised),
        TermValue("joined"),
    )


def test_sequential_dig_guarded_faces_without_join_stays_loud() -> None:
    from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
    from sugar_lift_py_tests.factory.build import default_catalog
    from sugar_lift_py_tests.floor import (
        GuardedFaces,
        GuardedReturn,
        GuardedScopeRebind,
    )
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.ir import make_var, not_
    from sugar_lift_py_tests.outcome import Complete

    guard = make_var("branch")

    class _UnjoinedFaces:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return Complete(
                GuardedFaces(
                    guard=guard,
                    entries=(
                        GuardedReturn((guard,), TermValue(7)),
                        GuardedScopeRebind(
                            (not_(guard),),
                            "answer",
                            TermValue(8),
                        ),
                    ),
                    then_exits=True,
                    else_exits=False,
                    can_fall_through=True,
                    continuation_guard=not_(guard),
                )
            )

    class _Fallback:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return Complete(ReturnValue(TermValue(0)))

    ctx = FactoryBuildContext(filename="wrong_twin.py", catalog=default_catalog())
    with pytest.raises(FactoryPanic):
        SequentialDigBody((_UnjoinedFaces(), _Fallback())).desugar(ctx)


def test_sequential_dig_mixed_guarded_exit_and_state_stays_loud() -> None:
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.ir import atomic, make_var, num
    from sugar_lift_py_tests.outcome import Complete

    guard = atomic("py.eq", [make_var("z"), num(1)])

    class _MixedOutcome:
        def contribution(self):
            return (
                GuardedReturn(guards=(guard,), value=TermValue(7)),
                ScopeRebind("state", TermValue(9)),
            )

        def extend_scope(self, ctx):
            return ctx

    class _MixedStatement:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return _MixedOutcome()

    class _FallbackReturnStatement:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return Complete(ReturnValue(TermValue(0)))

    fn_site = SourceFragment.from_source(
        "def f(z):\n    if z == 1:\n        return 7\n    return 0\n",
        "numpy/f2py/symbolic.py",
    ).statements()[0]
    with pytest.raises(FactoryPanic):
        SequentialDigBody(
            (_MixedStatement(), _FallbackReturnStatement()),
            fn_site=fn_site,
        ).desugar()


def test_sequential_dig_gap_prose_wrong_twin_panics() -> None:
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    fn_site = SourceFragment.from_source(
        "def f(x):\n    if x:\n        return 1\n", "numpy/_core/repro.py"
    ).statements()[0]
    with pytest.raises(FactoryPanic):
        SequentialDigBody((_NoReturnStatement(),), fn_site=fn_site).desugar()


def test_sequential_dig_propagates_a_named_runtime_effect() -> None:
    from sugar_lift_py_tests.effect import (
        DivisionByZeroRuntimeEffect,
        runtime_effect_evidence,
    )
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.outcome import Incomplete

    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    site = SourceFragment.from_source("x / y\n", "numpy/_core/repro.py").statements()[0]
    effect = DivisionByZeroRuntimeEffect(
        "numpy/_core/repro.py:21:8 division denominator is runtime-dependent",
        **runtime_effect_evidence("py.divide", make_var("denominator"), site),
    )

    class EffectStatement:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return Incomplete(effect)

    outcome = SequentialDigBody((EffectStatement(),)).desugar()

    assert isinstance(outcome, Incomplete)
    assert outcome.effect is effect
    assert "numpy/_core/repro.py:21:8" in outcome.reason


def test_contextmanager_dig_projects_exact_reduced_yield_operand() -> None:
    from sugar_lift_py_tests.effect import (
        GeneratorYieldRuntimeEffect,
        runtime_effect_evidence_from_terms,
    )
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.floor import BlockValue, SymbolicValue
    from sugar_lift_py_tests.ir import ctor, make_var, str_const
    from sugar_lift_py_tests.outcome import Complete, Incomplete

    site = (
        SourceFragment.from_source(
            "def manager():\n    yield 'entered'\n",
            "vendor/pkg/repro.py",
        )
        .statements()[0]
        .statements()[0]
        .function_body()[0]
    )
    yielded = str_const("entered")
    effect = GeneratorYieldRuntimeEffect(
        "generator suspension is runtime-dependent",
        **runtime_effect_evidence_from_terms(
            ctor("py.generator_yield", [yielded]),
            make_var("resume"),
            site,
        ),
    )

    class _ReducedTry:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return Complete(BlockValue((Incomplete(effect),)))

    outcome = SequentialDigBody(
        (_ReducedTry(),),
        contextmanager_yield=True,
    ).desugar()

    assert isinstance(outcome, Complete)
    assert outcome.value == SymbolicValue(yielded)


def test_generic_dig_cannot_project_contextmanager_yield_operand() -> None:
    from sugar_lift_py_tests.effect import (
        GeneratorYieldRuntimeEffect,
        runtime_effect_evidence_from_terms,
    )
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.floor import BlockValue
    from sugar_lift_py_tests.ir import ctor, make_var, str_const
    from sugar_lift_py_tests.outcome import Complete, Incomplete

    site = (
        SourceFragment.from_source(
            "def generator():\n    yield 'entered'\n",
            "vendor/pkg/wrong_twin.py",
        )
        .statements()[0]
        .statements()[0]
        .function_body()[0]
    )
    effect = GeneratorYieldRuntimeEffect(
        "generator suspension is runtime-dependent",
        **runtime_effect_evidence_from_terms(
            ctor("py.generator_yield", [str_const("entered")]),
            make_var("resume"),
            site,
        ),
    )

    class _ReducedTry:
        audit_row = None

        def reduce(self, ctx):
            del ctx
            return Complete(BlockValue((Incomplete(effect),)))

    with pytest.raises(FactoryPanic):
        SequentialDigBody((_ReducedTry(),)).desugar()


def test_source_contextmanager_authorizes_yield_projection() -> None:
    from sugar_lift_py_tests.context import FactoryBuildContext
    from sugar_lift_py_tests.factory import default_catalog
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.sugar.install_source_dig import (
        build_dig_body,
        contextmanager_exit_contract_for_fragment,
    )

    source = (
        "from contextlib import contextmanager\n"
        "\n"
        "@contextmanager\n"
        "def managed():\n"
        "    try:\n"
        "        yield 'entered'\n"
        "    finally:\n"
        "        cleanup()\n"
    )
    module = SourceFragment.from_source(source, "vendor/pkg/manager.py")
    fn_site = module.statements()[0].statements()[1]
    ctx = FactoryBuildContext(
        filename="vendor/pkg/manager.py",
        catalog=default_catalog(),
    )

    contract = contextmanager_exit_contract_for_fragment(fn_site)
    body = build_dig_body(fn_site, ctx)

    assert contract is not None
    assert contract.exception_names == frozenset()
    assert body.sugar.body.sugar.contextmanager_yield is True


def test_multiple_yields_cannot_authorize_contextmanager_projection() -> None:
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.sugar.install_source_dig import (
        contextmanager_exit_contract_for_fragment,
    )

    source = (
        "from contextlib import contextmanager\n"
        "\n"
        "@contextmanager\n"
        "def managed(flag):\n"
        "    try:\n"
        "        if flag:\n"
        "            yield 'first'\n"
        "        else:\n"
        "            yield 'second'\n"
        "    finally:\n"
        "        cleanup()\n"
    )
    module = SourceFragment.from_source(source, "vendor/pkg/wrong_twin.py")
    fn_site = module.statements()[0].statements()[1]

    assert contextmanager_exit_contract_for_fragment(fn_site) is None


def test_install_source_dig_never_constructs_abstract_runtime_effect() -> None:
    import ast
    import inspect
    import sugar_lift_py_tests.sugar.install_source_dig as subject

    tree = ast.parse(inspect.getsource(subject))
    direct = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "RuntimeEffect"
    ]
    assert direct == []
