"""Dependency-seat module memo + off-pin membrane.

Red instrument counts **frame-path** SourceFile constructions only
(``construction_context.frame_projection is True``). That is the door that
rebuilt enum.py 35× on one pandas/io/json/_json.py open (~45% of an ~85s wall).
Prefix fallthrough keeps a separate SourceFile per locus (unit target-pattern
state) and is not this memo's job.

Assertions:
  - frame-path SourceFile of enum.py == 0   (A membrane: off-pin cites, never rebuilds)
  - frame-path SourceFile of any module <= 1 (B memo: at most once per open)

B alone greens the <=1 tooth. A greens enum==0. Land B first if A needs design.
"""

from __future__ import annotations

import csv
import importlib.metadata
import sys
from collections import Counter
from pathlib import Path

import pytest

from sugar_lift_python_source import manager_construction as mc
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import resolve_source_visible_frame
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.tree import SourceFile as RealSourceFile


def _count_frame_path_sourcefiles(monkeypatch) -> Counter:
    """Count manager_construction.SourceFile builds with frame_projection=True."""
    counts: Counter = Counter()

    class CountingSourceFile(RealSourceFile):
        def __init__(self, identity, *args, **kwargs):
            ctx = kwargs.get("construction_context")
            if ctx is not None and getattr(ctx, "frame_projection", False):
                seat = identity[1] if isinstance(identity, tuple) else str(identity)
                counts[Path(seat).name] += 1
            super().__init__(identity, *args, **kwargs)

    monkeypatch.setattr(mc, "SourceFile", CountingSourceFile)
    return counts


def _install_two_export_module(root: Path) -> importlib.metadata.Distribution:
    """One module, two exported defs — without memo each frame resolve rebuilds SourceFile."""
    root.mkdir(parents=True, exist_ok=True)
    package = root / "memo_pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from memo_pkg.impl import first, second\n", encoding="utf-8"
    )
    (package / "impl.py").write_text(
        "def first(value):\n"
        "    return value\n"
        "\n"
        "def second(value):\n"
        "    return value + 1\n",
        encoding="utf-8",
    )
    metadata = root / "memo_pkg_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: memo-pkg-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text("memo_pkg\n", encoding="utf-8")
    recorded = (
        "memo_pkg/__init__.py",
        "memo_pkg/impl.py",
        "memo_pkg_dist-1.0.dist-info/METADATA",
        "memo_pkg_dist-1.0.dist-info/top_level.txt",
        "memo_pkg_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for path in recorded:
            writer.writerow((path, "", ""))
    sys.modules.pop("memo_pkg", None)
    sys.modules.pop("memo_pkg.impl", None)
    return importlib.metadata.Distribution.at(metadata)


def _receipts_for(root: Path, source: str):
    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts

    path = root / "consumer.py"
    path.write_text(source, encoding="utf-8")
    receipts, _ = authenticated_import_use_receipts(
        root, path, source, blake3_512_of(source.encode("utf-8")), module_identities={}
    )
    return receipts


def test_module_source_cid_memo_one_frame_sourcefile_for_two_defs(
    tmp_path: Path, monkeypatch
) -> None:
    """B: two definitions in one module frame-materialize SourceFile at most once."""
    counts = _count_frame_path_sourcefiles(monkeypatch)
    dist = _install_two_export_module(tmp_path / "site")
    graph = DependencyArtifactGraph.authenticate(dist)
    session = SourceResolutionSession()
    source = (
        "import memo_pkg\n"
        "memo_pkg.first(1)\n"
        "memo_pkg.second(2)\n"
    )
    receipts = _receipts_for(tmp_path, source)
    assert len(receipts) == 2

    for receipt in receipts:
        resolved = resolve_import_binding(receipt, graph=graph, session=session)
        assert isinstance(resolved, ResolvedPythonObjectV1)
        result = resolve_source_visible_frame(
            resolved, graph=graph, session=session
        )
        assert not isinstance(result, mc.ManagerConstructionGapV1), result

    assert counts.get("impl.py", 0) == 1, (
        f"memo failed: impl.py frame-path SourceFile constructions="
        f"{counts.get('impl.py', 0)}; all={dict(counts)}"
    )
    offenders = {name: n for name, n in counts.items() if n > 1}
    assert not offenders, (
        f"any module frame-path SourceFile must be <=1 per session; "
        f"offenders={offenders}"
    )


def test_pandas_json_open_one_session_and_module_memo(monkeypatch) -> None:
    """B live tooth: one open threads one session; any module SourceFile <=1 via memo.

    Pre-fix (profile): enum.py SourceFile n=35 on one open. Session-per-call
    made every module_pack die immediately. After: one session per open, enum=1.
    """
    from importlib import metadata

    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_python_source import resolution_session as rs

    session_n = 0
    _orig = rs.SourceResolutionSession.__init__

    def counting_init(self, *a, **k):
        nonlocal session_n
        session_n += 1
        return _orig(self, *a, **k)

    monkeypatch.setattr(rs.SourceResolutionSession, "__init__", counting_init)

    # Count ALL manager_construction.SourceFile builds (prefix + frame).
    counts: Counter = Counter()

    class CountingSourceFile(RealSourceFile):
        def __init__(self, identity, *args, **kwargs):
            seat = identity[1] if isinstance(identity, tuple) else str(identity)
            counts[Path(seat).name] += 1
            super().__init__(identity, *args, **kwargs)

    monkeypatch.setattr(mc, "SourceFile", CountingSourceFile)

    pandas_distribution = metadata.distribution("pandas")
    install_root = Path(pandas_distribution.locate_file("")).resolve()
    path = install_root / "pandas" / "io" / "json" / "_json.py"
    if not path.is_file():
        pytest.skip(f"pandas _json.py not installed at {path}")

    try:
        open_source_file_for_construction(
            path,
            root=install_root,
            construction_context=TreeConstructionContextV1.for_source_call_construction(),
            populate_derived=True,
        )
    except Exception:
        pass

    assert session_n == 1, (
        f"one SourceResolutionSession per open; got sessions={session_n}. "
        f"session_or_new(None) per nested resolve kills every module_pack."
    )
    enum_n = counts.get("enum.py", 0)
    assert enum_n <= 1, (
        f"memo: enum.py SourceFile must be <=1 per open; got {enum_n} "
        f"(pre-fix profile n=35). top={counts.most_common(15)}"
    )
    # Prefix and frame use different construction options, so dual-path modules
    # may appear twice (prefix_files + module_packs). Cap is 2, not unbounded.
    offenders = {name: n for name, n in counts.items() if n > 2}
    assert not offenders, (
        f"memo: no module SourceFile >2 per open (prefix+frame); "
        f"offenders={offenders}; top={counts.most_common(15)}"
    )


@pytest.mark.xfail(
    strict=True,
    reason="A membrane (off-pin stdlib cites, never rebuilds) not yet landed — B is memo only",
)
def test_pandas_json_open_off_pin_membrane_enum(monkeypatch) -> None:
    """A live tooth: off-pin stdlib enum.py is never frame-path rebuilt.

    Kept as xfail so the red instrument is enrolled; greens when A lands.
    """
    from importlib import metadata

    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    counts = _count_frame_path_sourcefiles(monkeypatch)
    pandas_distribution = metadata.distribution("pandas")
    install_root = Path(pandas_distribution.locate_file("")).resolve()
    path = install_root / "pandas" / "io" / "json" / "_json.py"
    if not path.is_file():
        pytest.skip(f"pandas _json.py not installed at {path}")

    try:
        open_source_file_for_construction(
            path,
            root=install_root,
            construction_context=TreeConstructionContextV1.for_source_call_construction(),
            populate_derived=True,
        )
    except Exception:
        pass

    enum_n = counts.get("enum.py", 0)
    assert enum_n == 0, (
        f"membrane: off-pin enum.py must never frame-rebuild; "
        f"frame-path constructions={enum_n} (pre-fix measured 35). "
        f"top={counts.most_common(15)}"
    )
