from __future__ import annotations

import ast
from dataclasses import replace

import pytest
from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.context.reduce_context import ReduceContext
from sugar_lift_py_tests.effect import genuine_runtime_operand
from sugar_lift_py_tests.factory import FactoryPanic, build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    BlockValue,
    ImportAliasValue,
    TermValue,
)
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.ir import ctor, make_var, py_truthy
from sugar_lift_py_tests.outcome import Complete, complete_value
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.temporal.temporal_context import TemporalContext


def _statement(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source).body[0], "imports.py")


def test_import_statement_constructs_every_named_binding() -> None:
    block = compose_block("    import numpy as np, pandas.core\n" "    return np\n")

    assert block.statements[:2] == (
        ImportAliasValue("numpy", "np"),
        ImportAliasValue("pandas.core", "pandas"),
    )


def test_importfrom_statement_constructs_aliases_and_relative_coordinates() -> None:
    built = build_node(
        ast.parse("from ..core import Series as S, DataFrame").body[0],
        filename="imports.py",
        role=SugarRole.STATEMENT,
    )
    value = complete_value(built.sugar.desugar(None), owner="test")

    assert value == BlockValue(
        (
            ImportAliasValue("..core.Series", "S"),
            ImportAliasValue("..core.DataFrame", "DataFrame"),
        )
    )


def test_importfrom_star_is_owned_by_star_importfrom_sugar() -> None:
    built = build_node(
        ast.parse("from pandas import *").body[0],
        filename="imports.py",
        role=SugarRole.STATEMENT,
    )
    assert type(built.sugar).__name__ == "StarImportFromSugar"
    assert [
        candidate.name
        for candidate in default_catalog().candidates_for(
            SugarRole.STATEMENT, _statement("from pandas import *")
        )
    ] == ["StarImportFromSugar"]


def test_import_alias_subscript_projects_its_import_coordinate() -> None:
    alias = ImportAliasValue("pandas._config.config._global_config", "cfg")

    outcome = alias.subscript(TermValue(0), _statement("import pandas"))
    value = complete_value(outcome, owner="test")

    assert value.to_term(owner="test").name == "py.subscript"
    assert value.to_term(owner="test").args[0] == alias.to_term(owner="test")


def test_module_import_alias_truth_constructs_true() -> None:
    """#4981: module objects are always truthy — construct, never py.truthy."""
    alias = ImportAliasValue("numpy", "np")
    site = _statement("import numpy as np")

    truth = complete_value(alias.truth(site), owner="test")

    assert isinstance(truth, TrueBoolLiteralSugar)


def test_ground_py_truthy_import_alias_cannot_mint_runtime_effect() -> None:
    """#4981 / #4265: ground import_alias truthiness has no RuntimeEffect door."""
    alias = ImportAliasValue("numpy", "np")
    ground = ctor("py.truthy", [alias.to_term(owner="test")])

    with pytest.raises(TypeError, match="genuine runtime-dependent operand"):
        genuine_runtime_operand("py.ifexp.select", ground)


def test_ifexp_over_module_import_alias_selects_true_branch() -> None:
    """#4981 live shape: ``a if import_alias else b`` constructs, not RuntimeEffect."""
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse('"pyarrow" if np else "python"', mode="eval").body
    body = ctx.build_body(SourceFragment.from_node(node, "t.py"), SugarRole.TERM)
    reduce_ctx = replace(
        ReduceContext.root(owner="if-exp-import-alias"),
        temporal=TemporalContext.empty().bind_value(
            "np", ImportAliasValue("numpy", "np")
        ),
    )

    outcome = body.reduce(reduce_ctx)

    assert isinstance(outcome, Complete)
    assert complete_value(outcome, owner="test") == StringValue("pyarrow")


def test_unresolved_from_import_truth_panics_not_runtime_effect() -> None:
    """#4981: HAS_PYARROW-style attribute import without dig is loud Construction."""
    alias = ImportAliasValue(
        "HAS_PYARROW",
        "HAS_PYARROW",
        import_target="pandas.compat.HAS_PYARROW",
    )
    site = _statement("from pandas.compat import HAS_PYARROW")

    with pytest.raises(FactoryPanic) as caught:
        alias.truth(site)

    assert caught.value.info.owner == "ImportAliasValue.truth"
    assert "RuntimeEffect" not in caught.value.info.owner
    assert "construct decidable import-alias truthiness" in caught.value.info.requested


def test_resolved_from_import_truth_delegates_to_value() -> None:
    alias = ImportAliasValue(
        "HAS_PYARROW",
        "HAS_PYARROW",
        import_target="pandas.compat.HAS_PYARROW",
        resolved_value=TrueBoolLiteralSugar(site=None),
    )
    site = _statement("from pandas.compat import HAS_PYARROW")

    truth = complete_value(alias.truth(site), owner="test")

    assert isinstance(truth, TrueBoolLiteralSugar)


def test_import_alias_can_ride_under_a_guard_without_changing_coordinate() -> None:
    alias = ImportAliasValue("pandas.compat.PY310", "PY310")

    assert alias.guarded(py_truthy(make_var("condition"))) is alias


def test_import_statement_owner_is_structural_and_star_is_excluded() -> None:
    catalog = default_catalog()
    assert [
        candidate.name
        for candidate in catalog.candidates_for(
            SugarRole.STATEMENT, _statement("import numpy as np, pandas")
        )
    ] == ["ImportSugar"]
    assert [
        candidate.name
        for candidate in catalog.candidates_for(
            SugarRole.STATEMENT, _statement("from pandas import Series as S")
        )
    ] == ["ImportFromSugar"]
    assert [
        candidate.name
        for candidate in catalog.candidates_for(
            SugarRole.STATEMENT, _statement("from pandas import *")
        )
    ] == ["StarImportFromSugar"]
