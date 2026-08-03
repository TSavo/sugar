"""Populate must not re-Materialize the consumer body just opened.

After open, ``populate_source_derived_resource_refs`` used to call
``authenticated_import_use_receipts`` which rebuilt a SourceFile for the same
``source_cid`` (profile showed absolute + relative ``_json.py`` seats, ~0.25s).
Pass the open module root into the lexical pass.
"""

from __future__ import annotations

from collections import Counter
from importlib import metadata
from pathlib import Path

import pytest

from sugar_source_tree.file_open_profile import (
    begin_file_open_profile,
    end_file_open_profile,
    summarize_module_materialize,
)


def test_json_open_plus_populate_materializes_consumer_once() -> None:
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    pandas_distribution = metadata.distribution("pandas")
    install_root = Path(pandas_distribution.locate_file("")).resolve()
    path = install_root / "pandas" / "io" / "json" / "_json.py"
    if not path.is_file():
        pytest.skip(f"pandas _json.py not installed at {path}")

    bag = begin_file_open_profile()
    try:
        sf = open_source_file_for_construction(
            path,
            root=install_root,
            construction_context=TreeConstructionContextV1.for_source_call_construction(),
            populate_derived=True,
            distribution="pandas",
            source_workspace_root=install_root,
        )
        fns = len(tuple(sf.functions()))
    finally:
        end_file_open_profile()

    summary = summarize_module_materialize(bag)
    json_rows = [
        row
        for row in (summary.get("top") or [])
        if str(row.get("module", "")).endswith("_json.py")
        or str(row.get("module", "")).endswith("/_json.py")
    ]
    json_calls = sum(int(row["count"]) for row in json_rows)
    assert json_calls <= 1, (
        f"_json.py MaterializeModule count={json_calls} (want ≤1); "
        f"rows={json_rows}; top={summary.get('top')}"
    )
    assert fns >= 40, f"_json open banked {fns} functions"
