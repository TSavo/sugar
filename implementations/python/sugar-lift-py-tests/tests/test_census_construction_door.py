"""Instrument law: package census uses the honest With construction door.

Bare ``SourceFile.from_path`` (no TreeConstructionContextV1) paints every
``with`` as ``RuntimeSelectedContextManager`` regardless of resolvability —
the false-red that made the 5021-site With residual one amorphous bucket.
``control_effect_recensus`` already uses ``open_source_file_for_construction``;
the package census must share that door so assertion-With mass is typed by
resolution gap / derived contract, not missing-context RuntimeSelected.
"""

from __future__ import annotations

from pathlib import Path


def test_census_unresolved_with_is_not_runtime_selected(tmp_path: Path) -> None:
    from sugar_lift_py_tests.census import census
    from sugar_source_tree.panic import RuntimeSelectedContextManager
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    path = tmp_path / "consumer.py"
    path.write_text(
        "def use_resource(manager):\n" "    with manager:\n" "        pass\n",
        encoding="utf-8",
    )
    # Honest door: typed residual, never unconditional RuntimeSelected.
    reporter = CollectingReporter()
    sf = open_source_file_for_construction(
        path, root=tmp_path, reporter=reporter, populate_derived=True
    )
    for fn in sf.functions():
        try:
            fn.sugar()
        except Exception:
            pass
    gap_types = {type(p).__name__ for _n, p in reporter.gaps}
    assert RuntimeSelectedContextManager.__name__ not in gap_types, gap_types
    assert gap_types, "expected a loud With residual under provisional context"

    # census() itself must call the honest door, not bare SourceFile.from_path.
    import ast
    import inspect
    import sugar_lift_py_tests.census as census_mod

    tree = ast.parse(inspect.getsource(census_mod.census))
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "open_source_file_for_construction" in names | calls
    assert "from_path" not in calls
    # Smoke: census returns without crash on the tiny package.
    rc = census(tmp_path)
    assert rc in (0, 1)
