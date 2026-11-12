"""A populate failure inside the one opener propagates (#7795).

History. #7062 and #7075 each stopped one exception class from erasing the
function count of a file whose SourceFile had already been built. The repair
that followed caught every ``Exception`` from populate inside
``open_source_file_for_construction`` and wrote it to ``populate_residuals``,
which nothing reads: the open "succeeded" and the halt was dropped.

The catch is deleted. A populate failure of any class reaches the caller, as it
does at the ``context-manager-resolutions`` level. The function count the board
reports comes from the ``functions`` level, which does not populate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.lift_rpc import (
    open_source_file_for_construction,
    tree_construction_context_for_workspace,
)
from sugar_source_tree.reporter import CollectingReporter


class _UnlistedPopulateDefect(Exception):
    """Third costume by construction: neither SugarNotWritten nor TypeError."""


def _write_three_functions(path: Path) -> None:
    path.write_text(
        "def one():\n"
        "    return 1\n"
        "\n"
        "def two():\n"
        "    return 2\n"
        "\n"
        "def three():\n"
        "    return 3\n",
        encoding="utf-8",
    )


def _open(tmp_path: Path, path: Path):
    ctx = tree_construction_context_for_workspace(tmp_path, contract_refs={})
    return open_source_file_for_construction(
        path,
        root=tmp_path,
        reporter=CollectingReporter(),
        construction_context=ctx,
        populate_derived=True,
        distribution="roster-floor-fixture",
        source_workspace_root=tmp_path,
    )


def test_unlisted_populate_exception_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A populate failure outside every historical allowlist reaches the caller."""
    path = tmp_path / "target.py"
    _write_three_functions(path)

    def boom_populate(source_file, **_k):
        del source_file
        raise _UnlistedPopulateDefect(
            "third costume: not SNW, not TypeError — allowlist cannot see me"
        )

    monkeypatch.setattr(
        "sugar_lift_python_source.manager_summary_derivation."
        "populate_source_derived_resource_refs",
        boom_populate,
    )

    with pytest.raises(_UnlistedPopulateDefect, match="third costume"):
        _open(tmp_path, path)


@pytest.mark.parametrize(
    "planted",
    [
        RuntimeError("populate runtime failure"),
        ValueError("populate value failure"),
    ],
)
def test_runtime_error_and_value_error_also_propagate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, planted: Exception
) -> None:
    """Two more Exception subclasses: the opener has no arm that keeps one."""
    path = tmp_path / "target.py"
    _write_three_functions(path)

    def boom(source_file, **_k):
        del source_file
        raise planted

    monkeypatch.setattr(
        "sugar_lift_python_source.manager_summary_derivation."
        "populate_source_derived_resource_refs",
        boom,
    )
    with pytest.raises(type(planted)):
        _open(tmp_path, path)


def test_open_path_failure_before_sourcefile_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An open that never builds its SourceFile raises, before any populate."""
    from sugar_source_tree.panic import SugarNotWritten
    import sugar_source_tree.tree as tree_mod

    path = tmp_path / "broken.py"
    path.write_text("def a():\n    return 1\n", encoding="utf-8")
    seed = tmp_path / "seed.py"
    seed.write_text("x = 1\n", encoding="utf-8")
    blame = tree_mod.SourceFile.from_path(seed).root.fragment

    def boom_init(self, *_a, **_k):
        raise SugarNotWritten(
            blame=blame,
            owner="open-path-gap",
            observed="SourceFile never constructed",
            requested="a constructed module",
            fix="repair open",
        )

    monkeypatch.setattr(tree_mod.SourceFile, "__init__", boom_init)
    with pytest.raises(SugarNotWritten):
        _open(tmp_path, path)


def test_successful_open_banks_floor_matching_functions(
    tmp_path: Path,
) -> None:
    """The truthful half: populate returns, and the open returns the file."""
    path = tmp_path / "target.py"
    _write_three_functions(path)
    source_file = _open(tmp_path, path)
    n = len(tuple(source_file.functions()))
    assert n == 3
    assert source_file.function_roster_floor == n
