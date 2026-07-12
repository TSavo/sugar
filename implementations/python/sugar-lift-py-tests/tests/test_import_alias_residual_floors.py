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
def test_diggable_import_binary_floor_panics_until_source_dig_is_wired(
    method: str, operator: str
) -> None:
    alias = ImportAliasValue("numpy", "np")
    other = TermValue(2)

    with pytest.raises(FactoryPanic, match="dig installed import source"):
        getattr(alias, method)(other, "alias.py:1")


@pytest.mark.parametrize(
    ("method", "operator"),
    [("unary_minus", "-"), ("unary_plus", "+"), ("bitwise_invert", "~")],
)
def test_diggable_import_unary_floor_cannot_mint_runtime_effect(
    method: str, operator: str
) -> None:
    alias = ImportAliasValue("numpy", "np")

    with pytest.raises(FactoryPanic, match="dig installed import source"):
        getattr(alias, method)("alias.py:1")


def test_import_alias_coordinate_remains_the_source_stated_binding() -> None:
    alias = ImportAliasValue("numpy", "np")
    term = alias.to_term(owner="test")

    assert term.name == "python:import_alias"
    assert [arg.value for arg in term.args] == ["np", "numpy"]


def test_unresolvable_native_import_floor_has_operand_witness() -> None:
    alias = ImportAliasValue("StringIO", "StringIO", import_target="_io.StringIO")

    outcome = alias.add(TermValue(1), "alias.py:1")
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, ImportedModuleRuntimeEffect)
    assert outcome.effect.witness.operand == alias.to_term(owner="test")
    assert outcome.effect.witness.locus == "alias.py:1"


def test_diggable_import_format_floor_panics() -> None:
    alias = ImportAliasValue("numpy", "np")

    with pytest.raises(FactoryPanic, match="dig installed import source"):
        alias.format_data_model(StringValue(""), "alias.py:1", None)


def test_genuinely_undefined_name_remains_loud() -> None:
    source = "def f():\n    return missing + 1\n"

    with pytest.raises(FactoryPanic, match="observed=missing requested=value"):
        audit_lift_file(source, "undefined.py", hold_panic=False)
