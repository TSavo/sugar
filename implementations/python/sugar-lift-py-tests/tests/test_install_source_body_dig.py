# SPDX-License-Identifier: MIT OR Apache-2.0
"""Install-source body dig: CallSugar attaches body when resolve succeeds."""

from __future__ import annotations

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
            status="selected",
            observed="If",
            blame="numpy/_core/repro.py:17:4",
            selected="IfSugar",
            candidates=["IfSugar"],
            message="selected IfSugar",
        )

    def reduce(self, ctx):
        del ctx
        return _NoReturnOutcome()


def test_sequential_dig_runtime_selected_return_is_a_named_effect() -> None:
    from sugar_lift_py_tests.effect import ConditionalExpressionRuntimeEffect
    from sugar_lift_py_tests.outcome import Incomplete

    outcome = SequentialDigBody((_NoReturnStatement(),)).desugar()

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, ConditionalExpressionRuntimeEffect)
    assert "numpy/_core/repro.py:17:4" in outcome.reason
    assert "If" in outcome.reason
    assert "runtime control flow" in outcome.reason


def test_sequential_dig_propagates_a_named_runtime_effect() -> None:
    from sugar_lift_py_tests.effect import DivisionByZeroRuntimeEffect
    from sugar_lift_py_tests.outcome import Incomplete

    effect = DivisionByZeroRuntimeEffect(
        "numpy/_core/repro.py:21:8 division denominator is runtime-dependent"
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
