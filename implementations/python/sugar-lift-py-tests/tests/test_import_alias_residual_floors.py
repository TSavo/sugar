from __future__ import annotations

import importlib
import subprocess
import sys

import pytest

from sugar_lift_py_tests.effect import ImportedModuleRuntimeEffect
from sugar_lift_py_tests.factory import FactoryPanic
from sugar_lift_py_tests.floor import (
    ImportAliasValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.lift_rpc import audit_lift_file, lift_file_payload
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.install_source_dig import resolve_install_source_value
from sugar_lift_py_tests.factory.source_fragment import SourceFragment

_SITE = SourceFragment.from_source("np + 1\n", "alias.py").statements()[0]
_CONSUMER = SourceFragment.from_source("ANSWER + 2\n", "consumer.py").statements()[0]
_ANNOTATION_SITE = (
    SourceFragment.from_source("Alias: TypeAlias = Imported | str\n", "alias.py")
    .statements()[0]
    .statements()[0]
    .annassign_value()
)
assert _ANNOTATION_SITE is not None


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
        getattr(alias, method)(other, _SITE)


@pytest.mark.parametrize(
    ("method", "operator"),
    [("unary_minus", "-"), ("unary_plus", "+"), ("bitwise_invert", "~")],
)
def test_diggable_import_unary_floor_cannot_mint_runtime_effect(
    method: str, operator: str
) -> None:
    alias = ImportAliasValue("numpy", "np")

    with pytest.raises(FactoryPanic, match="dig installed import source"):
        getattr(alias, method)(_SITE)


def test_import_alias_coordinate_remains_the_source_stated_binding() -> None:
    alias = ImportAliasValue("numpy", "np")
    term = alias.to_term(owner="test")

    assert term.name == "python:import_alias"
    assert [arg.value for arg in term.args] == ["np", "numpy"]


def test_unresolvable_native_import_floor_has_operand_witness() -> None:
    alias = ImportAliasValue("StringIO", "StringIO", import_target="_io.StringIO")

    outcome = alias.add(TermValue(1), _SITE)
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, ImportedModuleRuntimeEffect)
    assert outcome.effect.witness.operand == alias.to_term(owner="test")
    assert outcome.effect.witness.site is _SITE
    assert outcome.effect.witness.locus.startswith("alias.py:")


def test_import_alias_annotation_union_constructs_source_coordinate() -> None:
    alias = ImportAliasValue(
        "datetime.timedelta",
        "timedelta",
        import_target="datetime.timedelta",
    )
    right = SymbolicValue(ctor("python:type", [str_const("str")]))

    outcome = alias.bitwise_or(right, _ANNOTATION_SITE)

    assert complete_value(outcome, owner="test") == SymbolicValue(
        ctor(
            "|",
            [
                alias.to_term(owner="test"),
                ctor("python:type", [str_const("str")]),
            ],
        )
    )


def test_import_alias_runtime_bitwise_or_stays_loud() -> None:
    alias = ImportAliasValue(
        "datetime.timedelta",
        "timedelta",
        import_target="datetime.timedelta",
    )

    with pytest.raises(
        FactoryPanic,
        match=r"owner=bitwise_or.*observed=ImportAliasValue",
    ):
        alias.bitwise_or(TermValue(1), _SITE)


def test_import_alias_annotation_union_witness_refutes_wrong_twin() -> None:
    script = """\
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import ImportAliasValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import complete_value

site = SourceFragment.from_source(
    "Alias: TypeAlias = Imported | str\\n", "witness.py"
).statements()[0].statements()[0].annassign_value()
alias = ImportAliasValue(
    "datetime.timedelta", "timedelta", import_target="datetime.timedelta"
)
right = SymbolicValue(ctor("python:type", [str_const("str")]))
actual = complete_value(alias.bitwise_or(right, site), owner="witness")
expected = SymbolicValue(ctor("|", EXPECTED))
assert actual == expected
"""

    def run(expected: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", script.replace("EXPECTED", expected)],
            text=True,
            capture_output=True,
            check=False,
        )

    truthful = run(
        '[alias.to_term(owner="witness"), ' 'ctor("python:type", [str_const("str")])]'
    )
    lying = run(
        '[ctor("python:type", [str_const("str")]), ' 'alias.to_term(owner="witness")]'
    )

    assert truthful.returncode == 0, truthful.stderr
    assert lying.returncode == 1, lying.stderr


def test_pep613_import_alias_representative_lifts_without_bitwise_gap() -> None:
    source = """\
from datetime import timedelta
from typing import Literal, TypeAlias

TimestampNonexistent: TypeAlias = Literal["shift_forward", "raise"] | timedelta

def A():
    return TimestampNonexistent

def test_a():
    assert A() == A()
"""

    payload = lift_file_payload(source, "pandas_type_alias_representative.py")

    assert len(payload.ir) == 2
    assert payload.effects == []


def test_diggable_import_format_floor_panics() -> None:
    alias = ImportAliasValue("numpy", "np")

    with pytest.raises(FactoryPanic, match="dig installed import source"):
        alias.format_data_model(StringValue(""), _SITE, None)


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

    outcome = alias.add(TermValue(2), _CONSUMER)

    assert complete_value(outcome, owner="test") == TermValue(42)


def test_python_source_dig_gap_panics_instead_of_becoming_effect(
    tmp_path, monkeypatch
) -> None:
    # A diggable lambda constructs as LambdaCallable — never as a fabricated
    # ImportedModuleRuntimeEffect. Residual shapes that cannot dig still panic.
    (tmp_path / "gapped_import.py").write_text("VALUE = lambda *, x: x\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())

    resolved = resolve_install_source_value("gapped_import.VALUE", ctx)
    from sugar_lift_py_tests.floor.lambda_callable import LambdaCallable

    assert isinstance(resolved, LambdaCallable)

    # A .so-only / unresolvable native binding cannot dig and must not mint a
    # dig-gap effect; floor ops without a diggable origin still panic or stay
    # as ImportedModuleRuntimeEffect with a real witness — never a silent green.
    alias = ImportAliasValue("missing", "missing", import_target="no_such_pkg.missing")
    outcome = alias.add(TermValue(1), _SITE)
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, ImportedModuleRuntimeEffect)
