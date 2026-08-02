"""In-population prefix memo + L0c seat materialize once.

After membrane killed stdlib rebuilds, residual open cost on
``pandas/io/json/_json.py`` was ``pandas/_config/config.py`` MaterializeModule
dozens of times. L0c: process_resident + session memos → ≤1 construction.
Count constructions; do not time them.
"""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

import pytest

from sugar_source_tree.file_open_profile import (
    begin_file_open_profile,
    end_file_open_profile,
    summarize_module_materialize,
)
from sugar_source_tree.process_resident_file import (
    clear_process_resident_files,
    prepare_count_for,
)


def test_json_open_config_sourcefile_at_most_once() -> None:
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_source_tree.process_resident_file import _RESIDENT  # type: ignore

    pandas_distribution = metadata.distribution("pandas")
    install_root = Path(pandas_distribution.locate_file("")).resolve()
    path = install_root / "pandas" / "io" / "json" / "_json.py"
    if not path.is_file():
        pytest.skip(f"pandas _json.py not installed at {path}")

    clear_process_resident_files()
    bag = begin_file_open_profile()
    try:
        sf = open_source_file_for_construction(
            path,
            root=install_root,
            construction_context=TreeConstructionContextV1.for_source_call_construction(),
            populate_derived=True,
        )
        fns = len(tuple(sf.functions()))
    finally:
        end_file_open_profile()

    summary = summarize_module_materialize(bag)
    config_prepares = 0
    enum_prepares = 0
    for cid, ctx in list(_RESIDENT.items()):
        name = Path(str(ctx.filename)).name
        n = prepare_count_for(cid)
        if name == "config.py":
            config_prepares = max(config_prepares, n)
        if name == "enum.py":
            enum_prepares = max(enum_prepares, n)

    mat_config = 0
    mat_enum = 0
    for row in summary.get("top") or []:
        seats = [Path(str(s)).name for s in (row.get("seats") or [])]
        count = int(row.get("count") or 0)
        if "config.py" in seats or str(row.get("module", "")).endswith("config.py"):
            mat_config += count
        if "enum.py" in seats or str(row.get("module", "")).endswith("enum.py"):
            mat_enum += count

    assert config_prepares <= 1, (
        f"config.py prepare_count={config_prepares} (want ≤1); top={summary.get('top')}"
    )
    assert enum_prepares <= 1, (
        f"enum.py prepare_count={enum_prepares} (want ≤1); top={summary.get('top')}"
    )
    assert mat_config <= 1, (
        f"config.py MaterializeModule count={mat_config} (want ≤1); top={summary.get('top')}"
    )
    assert mat_enum <= 1, (
        f"enum.py MaterializeModule count={mat_enum} (want ≤1); top={summary.get('top')}"
    )
    assert fns >= 40, f"_json open banked {fns} functions"
