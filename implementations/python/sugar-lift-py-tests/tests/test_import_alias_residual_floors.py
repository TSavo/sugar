from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect import ImportedModuleRuntimeEffect
from sugar_lift_py_tests.factory import FactoryPanic
from sugar_lift_py_tests.floor import ImportAliasValue, StringValue, TermValue
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.lift_rpc import audit_lift_file


def _assert_import_effect(outcome, operator: str) -> None:
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, ImportedModuleRuntimeEffect)
    assert f"`np {operator}" in outcome.effect.reason
    assert "np -> numpy" in outcome.effect.reason


@pytest.mark.parametrize(
    ("method", "operator"),
    [
        ("add", "+"),
        ("subtract", "-"),
        ("multiply", "*"),
        ("divide", "/"),
        ("power", "**"),
        ("bitwise_and", "&"),
        ("bitwise_xor", "^"),
    ],
)
def test_import_alias_binary_floors_preserve_dynamic_module_effect(
    method: str, operator: str
) -> None:
    alias = ImportAliasValue("numpy", "np")
    other = TermValue(2)

    _assert_import_effect(getattr(alias, method)(other, "alias.py:1"), operator)


@pytest.mark.parametrize(
    ("method", "operator"),
    [("unary_minus", "-"), ("unary_plus", "+"), ("bitwise_invert", "~")],
)
def test_import_alias_unary_floors_preserve_dynamic_module_effect(
    method: str, operator: str
) -> None:
    alias = ImportAliasValue("numpy", "np")

    outcome = getattr(alias, method)("alias.py:1")
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, ImportedModuleRuntimeEffect)
    assert f"`{operator}np`" in outcome.effect.reason


def test_import_alias_coordinate_remains_the_source_stated_binding() -> None:
    alias = ImportAliasValue("numpy", "np")
    term = alias.to_term(owner="test")

    assert term.name == "python:import_alias"
    assert [arg.value for arg in term.args] == ["np", "numpy"]


def test_import_alias_format_floor_preserves_dynamic_module_effect() -> None:
    alias = ImportAliasValue("numpy", "np")

    outcome = alias.format_data_model(StringValue(""), "alias.py:1", None)
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, ImportedModuleRuntimeEffect)
    assert "`format(np, ...)`" in outcome.effect.reason


def test_genuinely_undefined_name_remains_loud() -> None:
    source = "def f():\n    return missing + 1\n"

    with pytest.raises(FactoryPanic, match="observed=missing requested=value"):
        audit_lift_file(source, "undefined.py", hold_panic=False)
