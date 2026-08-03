from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.import_binding import authenticated_import_value_use_receipts
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import AuthenticatedModuleSourceV1
from sugar_lift_python_source.manager_construction import (
    _retain_import_value_receipt_roster,
)
from sugar_source_tree.panic import BackendDefect

SOURCE = "from . import helper\nfirst = helper.FLAG\nsecond = helper.OTHER\n"


def _module_and_rows(root: Path, package: str):
    path = root / package / "__init__.py"
    path.parent.mkdir(parents=True)
    path.write_text(SOURCE, encoding="utf-8")
    source_cid = blake3_512_of(SOURCE.encode("utf-8"))
    rows, _ = authenticated_import_value_use_receipts(
        root, path, SOURCE, source_cid, module_identities={}
    )
    module = AuthenticatedModuleSourceV1(
        package, f"{package}/__init__.py", source_cid, SOURCE
    )
    return module, tuple(rows)


def test_identical_package_bytes_retain_distinct_authenticated_rosters(
    tmp_path: Path,
) -> None:
    first_module, first_rows = _module_and_rows(tmp_path, "first_package")
    second_module, second_rows = _module_and_rows(tmp_path, "second_package")
    context = TreeConstructionContextV1.for_source_call_construction()

    first = _retain_import_value_receipt_roster(context, first_module, first_rows)
    second = _retain_import_value_receipt_roster(context, second_module, second_rows)

    assert first is first_rows
    assert second is second_rows
    assert first is not second
    assert {row.target_symbol for row in first} != {row.target_symbol for row in second}
    assert {row.import_binding.cid for row in first}.isdisjoint(
        row.import_binding.cid for row in second
    )
    assert {row.use["cid"] for row in first}.isdisjoint(
        row.use["cid"] for row in second
    )
    assert len(first) == len(second) == 4


def test_same_module_reuses_objects_and_foreign_or_duplicate_rosters_refuse(
    tmp_path: Path,
) -> None:
    first_module, first_rows = _module_and_rows(tmp_path, "first_package")
    second_module, second_rows = _module_and_rows(tmp_path, "second_package")
    context = TreeConstructionContextV1.for_source_call_construction()
    retained = _retain_import_value_receipt_roster(context, first_module, first_rows)

    repeated = _retain_import_value_receipt_roster(
        context, first_module, tuple(first_rows)
    )
    assert repeated is retained
    assert all(left is right for left, right in zip(repeated, first_rows))

    with pytest.raises(BackendDefect, match="module identity"):
        _retain_import_value_receipt_roster(context, second_module, first_rows)
    with pytest.raises(BackendDefect, match="duplicate exact value-use row"):
        _retain_import_value_receipt_roster(
            TreeConstructionContextV1.for_source_call_construction(),
            first_module,
            (*first_rows, first_rows[-1]),
        )
    assert len(retained) == 4
    assert second_rows
