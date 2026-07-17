"""Star ``from`` imports construct exact bindings or stay loud."""

from __future__ import annotations

import ast
import sys

import pytest
from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import BlockValue, ImportAliasValue, ReturnValue
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.temporal import TemporalContext


def _statement(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source).body[0], "star_import.py")


def test_star_importfrom_owner_is_exactly_star_shape() -> None:
    catalog = default_catalog()
    assert [
        candidate.name
        for candidate in catalog.candidates_for(
            SugarRole.STATEMENT,
            _statement("from _datetime import *"),
        )
    ] == ["StarImportFromSugar"]
    assert "StarImportFromSugar" not in [
        candidate.name
        for candidate in catalog.candidates_for(
            SugarRole.STATEMENT,
            _statement("from operator import index as _index"),
        )
    ]
    assert "StarImportFromSugar" not in [
        candidate.name
        for candidate in catalog.candidates_for(
            SugarRole.STATEMENT,
            _statement("from operator import index"),
        )
    ]


def test_resolved_native_star_importfrom_constructs_public_bindings() -> None:
    built = build_node(
        ast.parse("from _datetime import *").body[0],
        filename="datetime.py",
        role=SugarRole.STATEMENT,
    )
    value = complete_value(built.sugar.desugar(None), owner="test")
    assert isinstance(value, BlockValue)
    assert {
        (entry.name, entry.bound_name, entry.import_target)
        for entry in value.statements
    } >= {
        ("_datetime.date", "date", "_datetime.date"),
        ("_datetime.datetime", "datetime", "_datetime.datetime"),
    }
    assert all(not entry.bound_name.startswith("_") for entry in value.statements)
    assert type(built.sugar).__name__ == "StarImportFromSugar"


def test_missing_star_importfrom_stays_loud() -> None:
    with pytest.raises(FactoryPanic, match="resolved static star-import exports"):
        build_node(
            ast.parse("from definitely_missing_sugar_module import *").body[0],
            filename="star_import.py",
            role=SugarRole.STATEMENT,
        )


def test_dynamic_source_manifest_stays_loud_without_module_execution(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "fixture_dynamic_star.py"
    module.write_text(
        'raise RuntimeError("must not execute")\n'
        "def exports():\n"
        '    return ["answer"]\n'
        "__all__ = exports()\n"
        "answer = 42\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(FactoryPanic, match="resolved static star-import exports"):
        build_node(
            ast.parse("from fixture_dynamic_star import *").body[0],
            filename="star_import.py",
            role=SugarRole.STATEMENT,
        )
    assert "fixture_dynamic_star" not in sys.modules


def test_operator_star_importfrom_binds_static_all_exports() -> None:
    """A module with a passive ``__all__`` expands into named import aliases."""
    built = build_node(
        ast.parse("from operator import *").body[0],
        filename="star_import.py",
        role=SugarRole.STATEMENT,
    )
    value = complete_value(built.sugar.desugar(None), owner="test")
    assert isinstance(value, BlockValue)
    assert value.statements  # operator ships a static __all__
    assert all(isinstance(entry, ImportAliasValue) for entry in value.statements)
    assert {entry.bound_name for entry in value.statements} >= {
        "add",
        "index",
        "itemgetter",
    }
    sample = next(entry for entry in value.statements if entry.bound_name == "index")
    assert sample.name == "operator.index"
    assert sample.import_target == "operator.index"


def test_datetime_try_star_importfrom_constructs_without_factory_panic() -> None:
    """Exact datetime CI shape: try/from _datetime import */except ImportError.

    CI failed with ``observed=ImportFrom`` at the star inside this try. Owning
    the star means TrySugar can construct; no RuntimeEffect papering.
    """
    source = (
        "try:\n"
        "    from _datetime import *\n"
        "except ImportError:\n"
        "    pass\n"
        "else:\n"
        "    from _datetime import __doc__\n"
    )
    catalog = default_catalog()
    ctx = FactoryBuildContext(
        filename="test_witness.py",
        catalog=catalog,
        temporal=TemporalContext.empty(),
    )
    built = build_node(
        ast.parse(source).body[0],
        filename="test_witness.py",
        role=SugarRole.STATEMENT,
        ctx=ctx,
    )
    assert type(built.sugar).__name__ == "TrySugar"
    # Construction is the gate CI hit; reduce under a real temporal so path join
    # has a scope (desugar(None) is not a production path).
    complete_value(built.sugar.desugar(ctx), owner="test")


def test_function_local_star_importfrom_composes_without_panic() -> None:
    block = compose_block(
        "    from _datetime import *\n" "    return 1\n",
    )
    returned = next(
        entry for entry in block.statements if isinstance(entry, ReturnValue)
    )
    assert returned.value.to_term(owner="test") is not None
