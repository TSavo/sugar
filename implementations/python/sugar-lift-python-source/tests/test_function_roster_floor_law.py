"""Roster-floor law: SourceFile N is a floor the board may not undercut silently.

#7062 fixed the SugarNotWritten arm. #7075 fixed the TypeError arm. Both are
costumes of one defect: a populate-path failure after a successful SourceFile
erased construction that already succeeded and banked functionsTotal=0 / fns=-1.

A third costume is whatever exception nobody listed. This instrument does not
extend an allowlist. It plants a failure *outside* the historical pair and
demands the open still returns the banked roster, with the failure named as a
populate residual.

Invariant (enforced at open_source_file_for_construction):

  If SourceFile produced N functions, the returned open may never lose those
  N functions because populate failed. Populate failure after the bank is a
  residual, not an empty denominator. Open-path failure *before* SourceFile
  still raises — correctly empty.
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


def test_unlisted_populate_exception_preserves_roster_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure outside the historical allowlist still keeps N and names why."""
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

    source_file = _open(tmp_path, path)
    assert len(tuple(source_file.functions())) == 3
    # Floor is banked as load-bearing state, not inferred after the fact.
    assert getattr(source_file, "function_roster_floor", None) == 3

    ctx = source_file.root.unit.construction_context
    residuals = list(getattr(ctx, "populate_residuals", None) or [])
    assert residuals, "populate failure must stay loud as a named residual"
    assert residuals[-1]["phase"] == "populate"
    assert residuals[-1]["type"] == "_UnlistedPopulateDefect"
    assert "third costume" in residuals[-1]["observed"]


def test_runtime_error_and_value_error_also_preserve_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two more unlisted Exception subclasses — the door is not a pair of arms."""
    path = tmp_path / "target.py"
    _write_three_functions(path)

    for exc in (
        RuntimeError("populate runtime residual"),
        ValueError("populate value residual"),
    ):

        def make_boom(planted):
            def boom(source_file, **_k):
                del source_file
                raise planted

            return boom

        monkeypatch.setattr(
            "sugar_lift_python_source.manager_summary_derivation."
            "populate_source_derived_resource_refs",
            make_boom(exc),
        )
        source_file = _open(tmp_path, path)
        assert len(tuple(source_file.functions())) == 3
        assert source_file.function_roster_floor == 3


def test_open_path_failure_before_sourcefile_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Floor law does not invent a denominator when SourceFile never built."""
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
    """Happy path: floor equals the live function roster."""
    path = tmp_path / "target.py"
    _write_three_functions(path)
    source_file = _open(tmp_path, path)
    n = len(tuple(source_file.functions()))
    assert n == 3
    assert source_file.function_roster_floor == n
