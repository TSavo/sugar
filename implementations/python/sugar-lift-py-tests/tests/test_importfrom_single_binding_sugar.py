"""Function-local single-name from imports bind their stated source address."""

from __future__ import annotations

import ast

import pytest
from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import ImportAliasValue, ReturnValue
from sugar_lift_py_tests.lift_rpc import audit_lift_file


def _statement(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source).body[0], "vendor.py")


def test_single_plain_from_import_binds_the_imported_address() -> None:
    block = compose_block(
        "    from pandas._testing import assert_produces_warning\n"
        "    return assert_produces_warning\n"
    )

    returned = next(
        entry for entry in block.statements if isinstance(entry, ReturnValue)
    )
    assert returned.value == ImportAliasValue(
        name="pandas._testing.assert_produces_warning",
        bound_name="assert_produces_warning",
    )


def test_other_from_import_partitions_stay_loud() -> None:
    for source in (
        "from pandas import Series as S",
        "from pandas import DataFrame, Series",
        "from .core import Series",
        "from pandas import *",
    ):
        with pytest.raises(FactoryPanic):
            build_node(
                ast.parse(source).body[0],
                filename="vendor.py",
                role=SugarRole.STATEMENT,
            )


def test_owner_is_exactly_single_plain_absolute_from_import() -> None:
    catalog = default_catalog()
    assert [
        candidate.name
        for candidate in catalog.candidates_for(
            SugarRole.STATEMENT,
            _statement("from pandas._testing import assert_produces_warning"),
        )
    ] == ["SingleImportFromSugar"]
    assert "SingleImportFromSugar" not in [
        candidate.name
        for candidate in catalog.candidates_for(
            SugarRole.STATEMENT,
            _statement("from pandas import DataFrame, Series"),
        )
    ]


def test_real_vendor_file_shape_has_no_importfrom_factory_panic() -> None:
    source = """
def raises_chained_assignment_error():
    from pandas._testing import assert_produces_warning
    return assert_produces_warning
"""
    recovered = audit_lift_file(
        source,
        "_testing/contexts.py",
        recover_panics=True,
    )
    assert all(panic.gap["observed"] != "ImportFrom" for panic in recovered.panics)
