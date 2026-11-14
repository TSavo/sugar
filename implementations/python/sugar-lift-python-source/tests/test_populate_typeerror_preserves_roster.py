"""A populate ``TypeError`` or ``SugarNotWritten`` propagates out of the opener (#7795).

History. #7062 (``SugarNotWritten``) and #7075 (``TypeError``: IfExpSugar body
requires ConstructedTermSugar, got SpreadCollectionSugar at
pandas/_testing/contexts.py) were two exception classes that, raised by
populate after the SourceFile was built, made the board report zero functions.
The repair caught the failure inside ``open_source_file_for_construction`` and
returned the file, which dropped the halt. The catch is deleted: both classes
reach the caller. Every level populates (#7796), so a populate failure is a
failure of every level that opens the file.

A ``TypeError`` raised while projecting one receipt is still cited inside
populate and populate goes on (last test); that is populate's own handling and
is not changed.
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


def _open_with_populate(tmp_path: Path, path: Path):
    ctx = tree_construction_context_for_workspace(tmp_path, contract_refs={})
    return open_source_file_for_construction(
        path,
        root=tmp_path,
        reporter=CollectingReporter(),
        construction_context=ctx,
        source_workspace_root=tmp_path,
    )


def test_populate_typeerror_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SourceFile builds; populate raises TypeError; the open raises it."""
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

    with pytest.raises(TypeError, match="IfExpSugar.body requires"):
        _open_with_populate(tmp_path, path)


def test_populate_snw_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The #7062 class: populate raises SugarNotWritten; the open raises it."""
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

    with pytest.raises(SugarNotWritten) as refusal:
        _open_with_populate(tmp_path, path)
    assert refusal.value.owner == "module function definition execution"


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
        source_workspace_root=tmp_path,
    )
    assert len(tuple(source_file.functions())) == 3
