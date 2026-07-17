from __future__ import annotations

import importlib
import subprocess
import sys

import pytest

from sugar_lift_py_tests.effect import ImportedModuleRuntimeEffect
from sugar_lift_py_tests.factory import FactoryPanic
from sugar_lift_py_tests.floor import (
    FunctionCallable,
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
from sugar_lift_py_tests.sugar.getattr_builtin_sugar import GetattrBuiltinSugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.idd.sugar_witness_instruments import evaluate_seed_witnesses
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


def test_setup_sentinel_false_branch_reexport_digs_exact_function(
    tmp_path, monkeypatch
) -> None:
    package = tmp_path / "witnessed_reexport"
    package.mkdir()
    (package / "__init__.py").write_text(
        "try:\n"
        "    __WITNESSED_SETUP__\n"
        "except NameError:\n"
        "    __WITNESSED_SETUP__ = False\n"
        "if __WITNESSED_SETUP__:\n"
        "    pass\n"
        "else:\n"
        "    from .core import selected\n"
    )
    (package / "core.py").write_text("def selected(value):\n" "    return value\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())

    resolved = resolve_install_source_value("witnessed_reexport.selected", ctx)

    assert isinstance(resolved, FunctionCallable)
    assert resolved.name == "witnessed_reexport.core.selected"


def test_unconditional_reexport_digs_exact_constructed_value(
    tmp_path, monkeypatch
) -> None:
    package = tmp_path / "witnessed_value_reexport"
    package.mkdir()
    (package / "__init__.py").write_text("from .constants import FLAG\n")
    (package / "constants.py").write_text("FLAG = False\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())

    resolved = resolve_install_source_value("witnessed_value_reexport.FLAG", ctx)

    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )

    assert isinstance(resolved, FalseBoolLiteralSugar)


def test_shadowed_unconditional_reexport_stays_unresolved(
    tmp_path, monkeypatch
) -> None:
    package = tmp_path / "shadowed_value_reexport"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from .constants import FLAG\n" "FLAG = choose_at_runtime()\n"
    )
    (package / "constants.py").write_text("FLAG = False\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())

    resolved = resolve_install_source_value("shadowed_value_reexport.FLAG", ctx)

    from sugar_lift_py_tests.floor import CallSiteValue

    assert isinstance(resolved, CallSiteValue)
    assert resolved.target_name == "choose_at_runtime"


def test_literal_all_star_reexport_digs_exact_constructed_value(
    tmp_path, monkeypatch
) -> None:
    package = tmp_path / "witnessed_star_reexport"
    package.mkdir()
    (package / "__init__.py").write_text(
        "# literal star export\n" "from .constants import *\n"
    )
    (package / "constants.py").write_text("__all__ = ['FLAG']\n" "FLAG = False\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())

    resolved = resolve_install_source_value("witnessed_star_reexport.FLAG", ctx)

    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )

    assert isinstance(resolved, FalseBoolLiteralSugar)


def test_star_reexport_without_literal_all_stays_unresolved(
    tmp_path, monkeypatch
) -> None:
    package = tmp_path / "opaque_star_reexport"
    package.mkdir()
    (package / "__init__.py").write_text(
        "# opaque star export\n" "from .constants import *\n"
    )
    (package / "constants.py").write_text(
        "__all__ = exported_at_runtime()\n" "FLAG = False\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())

    assert resolve_install_source_value("opaque_star_reexport.FLAG", ctx) is None


def test_shadowed_literal_all_star_reexport_uses_later_binding(
    tmp_path, monkeypatch
) -> None:
    package = tmp_path / "shadowed_star_reexport"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from .constants import *\n" "FLAG = choose_at_runtime()\n"
    )
    (package / "constants.py").write_text("__all__ = ['FLAG']\n" "FLAG = False\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())

    resolved = resolve_install_source_value("shadowed_star_reexport.FLAG", ctx)

    from sugar_lift_py_tests.floor import CallSiteValue

    assert isinstance(resolved, CallSiteValue)
    assert resolved.target_name == "choose_at_runtime"


def test_pandas_compat_reexport_constructs_underlying_predicate() -> None:
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())

    resolved = resolve_install_source_value("pandas.compat.IS64", ctx)

    from sugar_lift_py_tests.floor import PredicateValue

    assert isinstance(resolved, PredicateValue)
    assert resolved.formula.name == "py.gt"


def test_try_except_module_binding_constructs_guarded_value(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "try_selected_value.py").write_text(
        "try:\n"
        "    import optional_dependency\n"
        "    FLAG = True\n"
        "except ImportError:\n"
        "    FLAG = False\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())

    resolved = resolve_install_source_value("try_selected_value.FLAG", ctx)

    from sugar_lift_py_tests.floor import GuardedValue
    from sugar_lift_py_tests.ir import atomic, not_, str_const
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    assert isinstance(resolved, GuardedValue)
    assert resolved.guard == not_(atomic("py.except", [str_const("ImportError")]))
    assert isinstance(resolved.when_true, TrueBoolLiteralSugar)
    assert isinstance(resolved.when_false, FalseBoolLiteralSugar)


def test_try_except_module_binding_missing_from_one_path_stays_unresolved(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "partial_try_selected_value.py").write_text(
        "try:\n"
        "    import optional_dependency\n"
        "    FLAG = True\n"
        "except ImportError:\n"
        "    pass\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())

    assert resolve_install_source_value("partial_try_selected_value.FLAG", ctx) is None


def test_pandas_pyarrow_flag_constructs_guarded_predicate() -> None:
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())

    resolved = resolve_install_source_value(
        "pandas.compat.pyarrow.HAS_PYARROW",
        ctx,
    )

    from sugar_lift_py_tests.floor import GuardedValue, PredicateValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )

    assert isinstance(resolved, GuardedValue)
    assert isinstance(resolved.when_true, PredicateValue)
    assert resolved.when_true.formula.name == "py.ge"
    assert isinstance(resolved.when_false, FalseBoolLiteralSugar)


def test_unconditional_reexport_truth_witness_refutes_wrong_twin(tmp_path) -> None:
    prefix = (
        "from pip._vendor.urllib3.util import IS_PYOPENSSL\n\n"
        "def A():\n"
        "    return not IS_PYOPENSSL\n\n"
    )
    witness = _call_pair(
        name="unconditional_reexport_truth",
        owner_sugar="UnaryOpSugar",
        truthful=prefix + "def test_a():\n    assert A() == True\n",
        lying=prefix + "def test_a():\n    assert A() == False\n",
    )

    assert evaluate_seed_witnesses((witness,), tmp_path).is_zero


def test_numpy_setup_reexport_getattr_constructs_exact_import_coordinate() -> None:
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())
    alias = ImportAliasValue("numpy", "np", import_target="numpy")
    sugar = GetattrBuiltinSugar(None, "sum", None, None, _SITE)  # type: ignore[arg-type]

    outcome = sugar._finish_static(alias, "sum", ctx)
    resolved = complete_value(outcome, owner="numpy setup reexport")

    assert isinstance(resolved, ImportAliasValue)
    assert resolved.import_target == "numpy._core.sum"


def test_imported_source_getattr_witness_truthful_sat_and_lying_unsat(
    tmp_path,
) -> None:
    witness = next(
        pair
        for pair in GetattrBuiltinSugar.witnesses()
        if pair.name == "getattr_imported_source_function_return"
    )

    assert evaluate_seed_witnesses((witness,), tmp_path).is_zero


def test_runtime_selected_reexport_branch_stays_loud(tmp_path, monkeypatch) -> None:
    package = tmp_path / "runtime_reexport"
    package.mkdir()
    (package / "__init__.py").write_text(
        "if choose_at_runtime():\n" "    from .core import selected\n"
    )
    (package / "core.py").write_text("def selected(value):\n" "    return value\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())

    assert resolve_install_source_value("runtime_reexport.selected", ctx) is None


def test_prebound_setup_sentinel_does_not_claim_false_branch(
    tmp_path, monkeypatch
) -> None:
    package = tmp_path / "prebound_reexport"
    package.mkdir()
    (package / "__init__.py").write_text(
        "__SETUP__ = True\n"
        "try:\n"
        "    __SETUP__\n"
        "except NameError:\n"
        "    __SETUP__ = False\n"
        "if __SETUP__:\n"
        "    pass\n"
        "else:\n"
        "    from .core import selected\n"
    )
    (package / "core.py").write_text("def selected(value):\n" "    return value\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())

    assert resolve_install_source_value("prebound_reexport.selected", ctx) is None


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
