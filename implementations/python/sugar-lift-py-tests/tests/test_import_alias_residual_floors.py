from __future__ import annotations

import importlib

import pytest

from sugar_lift_py_tests.effect import ImportedModuleRuntimeEffect
from sugar_lift_py_tests.factory import FactoryPanic
from sugar_lift_py_tests.floor import ImportAliasValue, StringValue, TermValue
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.install_source_dig import resolve_install_source_value


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


def test_python_source_constant_digs_and_constructs_through_floor_op(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "witnessed_import.py").write_text("ANSWER = 40\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())
    resolved = resolve_install_source_value("witnessed_import.ANSWER", ctx)
    alias = ImportAliasValue(
        "ANSWER",
        "ANSWER",
        import_target="witnessed_import.ANSWER",
        resolved_value=resolved,
    )

    outcome = alias.add(TermValue(2), "consumer.py:1")

    assert complete_value(outcome, owner="test") == TermValue(42)


def test_python_source_dig_gap_panics_instead_of_becoming_effect(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "gapped_import.py").write_text(
        "VALUE = lambda *, x: x\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())

    with pytest.raises(FactoryPanic):
        resolve_install_source_value("gapped_import.VALUE", ctx)
