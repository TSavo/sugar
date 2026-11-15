"""A failure inside the one opener propagates (#7795).

The opener catches nothing: an open that never builds its SourceFile raises.
The function count the board reports comes from the ``functions`` level.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.lift_rpc import (
    open_source_file_for_construction,
    tree_construction_context_for_workspace,
)
from sugar_source_tree.reporter import CollectingReporter


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
    ctx = tree_construction_context_for_workspace(tmp_path)
    return open_source_file_for_construction(
        path,
        root=tmp_path,
        reporter=CollectingReporter(),
        construction_context=ctx,
        source_workspace_root=tmp_path,
    )


def test_open_path_failure_before_sourcefile_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An open that never builds its SourceFile raises."""
    from sugar_lift_py_tests.lift_rpc import _open_at_seat
    from sugar_source_tree.panic import SugarNotWritten
    import sugar_source_tree.process_resident_file as residency

    path = tmp_path / "broken.py"
    path.write_text("def a():\n    return 1\n", encoding="utf-8")
    seed = tmp_path / "seed.py"
    seed.write_text("x = 1\n", encoding="utf-8")
    blame = _open_at_seat(seed, root=tmp_path).root.fragment
    fired = {"n": 0}

    def boom_open(*_a, **_k):
        fired["n"] += 1
        raise SugarNotWritten(
            blame=blame,
            owner="open-path-gap",
            observed="SourceFile never constructed",
            requested="a constructed module",
            fix="repair open",
        )

    # The residency door every open walks (``_open_at_seat`` ->
    # ``_source_file_from_identity``).
    monkeypatch.setattr(residency, "_source_file_from_identity", boom_open)
    with pytest.raises(SugarNotWritten) as refusal:
        _open(tmp_path, path)
    assert fired["n"] > 0
    assert refusal.value.owner == "open-path-gap"


def test_successful_open_returns_the_file_with_its_functions(
    tmp_path: Path,
) -> None:
    """The truthful half: the open returns the file."""
    path = tmp_path / "target.py"
    _write_three_functions(path)
    source_file = _open(tmp_path, path)
    assert len(tuple(source_file.functions())) == 3
