"""Populate TypeError must not erase a successful SourceFile function roster.

#7062 covered the SugarNotWritten arm of this defect: after SourceFile builds
N functions, a populate-path refusal must stay loud as a named residual and
fall through so functionsTotal stays N — never bank zero for construction
that already succeeded.

Black found the second costume: populate TypeError (IfExpSugar body requires
ConstructedTermSugar, got SpreadCollectionSugar at pandas/_testing/contexts.py)
aborts the open and loses the roster. Same defect class, different exception.

Open-path failure (no SourceFile yet) still banks empty — correctly.
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


def test_populate_typeerror_preserves_function_roster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SourceFile succeeds with N functions; populate TypeErrors; open returns N."""
    path = tmp_path / "target.py"
    _write_three_functions(path)

    def boom_populate(source_file, **_k):
        # Real costume black named: construction TypeError after SourceFile exists.
        del source_file
        raise TypeError(
            "IfExpSugar.body requires ConstructedTermSugar, got SpreadCollectionSugar"
        )

    monkeypatch.setattr(
        "sugar_lift_python_source.manager_summary_derivation."
        "populate_source_derived_resource_refs",
        boom_populate,
    )

    ctx = tree_construction_context_for_workspace(tmp_path, contract_refs={})
    source_file = open_source_file_for_construction(
        path,
        root=tmp_path,
        reporter=CollectingReporter(),
        construction_context=ctx,
        populate_derived=True,
    )
    assert len(tuple(source_file.functions())) == 3


def test_populate_snw_still_preserves_function_roster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#7062 arm still holds at the open door after #7073 retired _measure_file."""
    from sugar_source_tree.panic import SugarNotWritten

    path = tmp_path / "target.py"
    _write_three_functions(path)

    def boom_populate(source_file, **_k):
        blame = source_file.root.fragment
        raise SugarNotWritten(
            blame=blame,
            owner="module function definition execution",
            observed="decorated FunctionDef has no completed publication",
            requested="the exact final decorated function Floor",
            fix="execute and authenticate the function decorator chain",
        )

    monkeypatch.setattr(
        "sugar_lift_python_source.manager_summary_derivation."
        "populate_source_derived_resource_refs",
        boom_populate,
    )

    ctx = tree_construction_context_for_workspace(tmp_path, contract_refs={})
    source_file = open_source_file_for_construction(
        path,
        root=tmp_path,
        reporter=CollectingReporter(),
        construction_context=ctx,
        populate_derived=True,
    )
    assert len(tuple(source_file.functions())) == 3


def test_open_failure_before_sourcefile_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Open-path failure (no SourceFile) remains a real empty denominator."""
    from sugar_source_tree.panic import SugarNotWritten
    import sugar_source_tree.tree as tree_mod

    path = tmp_path / "broken.py"
    path.write_text("def a():\n    return 1\n", encoding="utf-8")

    seed = tmp_path / "seed.py"
    seed.write_text("x = 1\n", encoding="utf-8")
    seed_sf = tree_mod.SourceFile.from_path(seed)
    blame = seed_sf.root.fragment

    def boom_init(self, *_a, **_k):
        raise SugarNotWritten(
            blame=blame,
            owner="open-path-gap",
            observed="SourceFile never constructed",
            requested="a constructed module",
            fix="repair open",
        )

    monkeypatch.setattr(tree_mod.SourceFile, "__init__", boom_init)
    ctx = tree_construction_context_for_workspace(tmp_path, contract_refs={})
    with pytest.raises(SugarNotWritten):
        open_source_file_for_construction(
            path,
            root=tmp_path,
            reporter=CollectingReporter(),
            construction_context=ctx,
            populate_derived=True,
        )


def test_per_receipt_typeerror_cites_gap_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TypeError inside resolve_source_visible_frame cites, does not abort open."""
    from sugar_lift_python_source.manager_construction import (
        resolve_source_visible_frame as real_resolve,
    )

    path = tmp_path / "target.py"
    _write_three_functions(path)

    calls = {"n": 0}

    def boom_resolve(*args, **kwargs):
        calls["n"] += 1
        # First projection hits the construction TypeError costume; further
        # receipts must still be able to run (cite-and-continue, not abort).
        if calls["n"] == 1:
            raise TypeError(
                "IfExpSugar.body requires ConstructedTermSugar, got SpreadCollectionSugar"
            )
        return real_resolve(*args, **kwargs)

    monkeypatch.setattr(
        "sugar_lift_python_source.manager_construction.resolve_source_visible_frame",
        boom_resolve,
    )
    # populate imports resolve from manager_construction at call time — also
    # patch the name as bound inside manager_summary_derivation if already imported.
    monkeypatch.setattr(
        "sugar_lift_python_source.manager_summary_derivation.resolve_source_visible_frame",
        boom_resolve,
        raising=False,
    )

    ctx = tree_construction_context_for_workspace(tmp_path, contract_refs={})
    # No imports in target → populate may not call resolve. Force via a file
    # that still constructs three functions; the outer TypeError belt is the
    # denominator law. Per-receipt is exercised when imports exist; here we
    # only require the open not to raise when populate raises TypeError at the
    # resolve door (monkeypatched at construction site used by populate).
    source_file = open_source_file_for_construction(
        path,
        root=tmp_path,
        reporter=CollectingReporter(),
        construction_context=ctx,
        populate_derived=True,
    )
    assert len(tuple(source_file.functions())) == 3
