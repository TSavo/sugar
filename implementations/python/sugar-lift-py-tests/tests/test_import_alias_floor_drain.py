from __future__ import annotations

import ast

import pytest
from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    BlockValue,
    ImportAliasValue,
    PredicateValue,
    TermValue,
)
from sugar_lift_py_tests.ir import make_var, py_truthy
from sugar_lift_py_tests.outcome import Complete, complete_value


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


def test_importfrom_star_remains_a_loud_construction_gap() -> None:
    with pytest.raises(FactoryPanic, match="None => panic"):
        build_node(
            ast.parse("from pandas import *").body[0],
            filename="imports.py",
            role=SugarRole.STATEMENT,
        )


def test_import_alias_subscript_projects_its_import_coordinate() -> None:
    alias = ImportAliasValue("pandas._config.config._global_config", "cfg")

    outcome = alias.subscript(TermValue(0), _statement("import pandas"))
    value = complete_value(outcome, owner="test")

    assert value.to_term(owner="test").name == "py.subscript"
    assert value.to_term(owner="test").args[0] == alias.to_term(owner="test")


def test_import_alias_truth_projects_python_truthiness() -> None:
    alias = ImportAliasValue("pandas.compat.PY310", "PY310")

    predicate = complete_value(alias.truth(_statement("import pandas")), owner="test")

    assert isinstance(predicate, PredicateValue)
    assert predicate.formula == py_truthy(alias.to_term(owner="test"))


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
    assert not list(
        catalog.candidates_for(SugarRole.STATEMENT, _statement("from pandas import *"))
    )
