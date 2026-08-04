"""L0c: dependency seat materialize at most once per open.

Doors (black owns these keys alone):
  - process_resident under whole-file content CID
  - session module_materialize under authenticated module key

Tooth: one open of pandas/io/json/_json.py → enum ≤1 and config ≤1
constructions. Count constructions; do not time them.
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
    resident_size,
)


def _install_root() -> Path:
    return Path(metadata.distribution("pandas").locate_file("")).resolve()


def test_same_content_same_seat_hits_alternate_seat_misses() -> None:
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.tree import SourceFile

    clear_process_resident_files()
    body = "def f():\n    return 1\n"
    cid = blake3_512_of(body.encode("utf-8"))
    first = SourceFile((body, "seat_0/enum.py", cid))
    repeat = SourceFile((body, "seat_0/enum.py", cid))
    alternate = SourceFile((body, "seat_1/enum.py", cid))
    assert repeat is first
    assert alternate is not first
    assert prepare_count_for(cid, "seat_0/enum.py") == 1
    assert prepare_count_for(cid, "seat_1/enum.py") == 1
    assert resident_size() == 2


def test_sourcefile_constructor_returns_resident_identity() -> None:
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.tree import SourceFile

    clear_process_resident_files()
    body = "x = 1\n"
    cid = blake3_512_of(body.encode("utf-8"))
    a = SourceFile((body, "pkg/a.py", cid))
    b = SourceFile((body, "other/a.py", cid))
    assert a is not b
    assert prepare_count_for(cid, "pkg/a.py") == 1
    assert prepare_count_for(cid, "other/a.py") == 1


def test_json_open_enum_and_config_at_most_once() -> None:
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_source_tree.process_resident_file import _RESIDENT  # type: ignore

    install_root = _install_root()
    path = install_root / "pandas" / "io" / "json" / "_json.py"
    if not path.is_file():
        pytest.skip(f"pandas _json.py not installed at {path}")

    clear_process_resident_files()
    bag = begin_file_open_profile()
    try:
        sf = open_source_file_for_construction(
            path,
            root=install_root,
            distribution="pandas",
            construction_context=TreeConstructionContextV1.for_source_call_construction(),
            populate_derived=True,
        )
        fns = len(tuple(sf.functions()))
    finally:
        end_file_open_profile()

    summary = summarize_module_materialize(bag)

    enum_prepares = 0
    config_prepares = 0
    for cid, ctx in list(_RESIDENT.items()):
        name = Path(str(ctx.filename)).name
        n = prepare_count_for(cid)
        if name == "enum.py":
            enum_prepares = max(enum_prepares, n)
        if name == "config.py":
            config_prepares = max(config_prepares, n)

    mat_enum = 0
    mat_config = 0
    for row in summary.get("top") or []:
        seats = [Path(str(s)).name for s in (row.get("seats") or [])]
        count = int(row.get("count") or 0)
        if "enum.py" in seats or str(row.get("module", "")).endswith("enum.py"):
            mat_enum += count
        if "config.py" in seats or str(row.get("module", "")).endswith("config.py"):
            mat_config += count

    assert enum_prepares <= 1, (
        f"L0c FAIL: enum.py prepare_count={enum_prepares} (want ≤1); "
        f"mat_top={summary.get('top')}"
    )
    assert config_prepares <= 1, (
        f"L0c FAIL: config.py prepare_count={config_prepares} (want ≤1); "
        f"mat_top={summary.get('top')}"
    )
    assert mat_enum <= 1, (
        f"L0c FAIL: enum.py MaterializeModule count={mat_enum} (want ≤1); "
        f"top={summary.get('top')}"
    )
    assert mat_config <= 1, (
        f"L0c FAIL: config.py MaterializeModule count={mat_config} (want ≤1); "
        f"top={summary.get('top')}"
    )
    assert fns >= 40, f"_json open banked {fns} functions (roster floor)"
