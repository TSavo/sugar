"""In-population prefix memo: one session → config SourceFile not ×N.

After membrane (#7057) killed stdlib rebuilds, residual open cost on
``pandas/io/json/_json.py`` was ``pandas/_config/config.py`` MaterializeModule
dozens of times via ``prefix_has_completed_fallthrough`` →
``_module_prefix_outcome`` (export fallthrough once per locus).

Frame-door module memo is #7064. This tooth owns the **prefix door** on the
same ``SourceResolutionSession`` (file-open already threads one session).

Values stay session-owned (context-bound). No process-global projection memo.
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
from sugar_source_tree.tree import SourceFile as RealSourceFile


def test_json_open_config_sourcefile_not_dozens(monkeypatch) -> None:
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_source_tree import tree as tree_mod

    pandas_distribution = metadata.distribution("pandas")
    install_root = Path(pandas_distribution.locate_file("")).resolve()
    path = install_root / "pandas" / "io" / "json" / "_json.py"
    if not path.is_file():
        pytest.skip(f"pandas _json.py not installed at {path}")

    builds: Counter = Counter()
    orig = tree_mod.SourceFile.__init__

    def counting(self, identity, *args, **kwargs):
        seat = identity[1] if isinstance(identity, tuple) else str(identity)
        builds[Path(str(seat)).name] += 1
        return orig(self, identity, *args, **kwargs)

    monkeypatch.setattr(tree_mod.SourceFile, "__init__", counting)

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
    config_sf = builds.get("config.py", 0)
    config_mat = sum(
        int(row["count"])
        for row in (summary.get("top") or [])
        if str(row["module"]).endswith("config.py")
    )
    # Pre-fix residual: SourceFile config.py dozens (33 measured). After:
    # prefix door 1 + frame door 1 + lexical use/value mints ≤2.
    assert config_sf <= 4, (
        f"config.py SourceFile constructions={config_sf} (want ≤4); "
        f"all={dict(builds)}; mat_top={summary.get('top')}"
    )
    assert config_mat <= 4, (
        f"config.py MaterializeModule count={config_mat} (want ≤4); "
        f"top={summary.get('top')}"
    )
    # False-zero floor: open must keep the real function roster.
    assert fns >= 40, f"_json open banked {fns} functions"
