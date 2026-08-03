"""Reachable-only source-frame construction.

``_resolve_source_visible_frame_uncached`` constructs only the authenticated
target's local definition graph. Unrelated module classes must not abort the
target frame. Unrelated-class panics stay loud when that definition *is* the
target (or is actually reached). Compare leg-site panics are never weakened.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.source_call_resolution import (
    SourceCallPreconstructionGapV1,
    SourceCallPreconstructionRefV1,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_call_preconstruction import (
    populate_source_visible_call_frames,
)
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.nodes import Call as SourceCall
from sugar_source_tree.tree import SourceFile


def _distribution(root: Path, package: str, module_source: str, export: str):
    pkg = root / package
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        f"from {package}.mod import {export}\n", encoding="utf-8"
    )
    (pkg / "mod.py").write_text(module_source, encoding="utf-8")
    meta = root / f"{package}_dist-1.0.dist-info"
    meta.mkdir()
    (meta / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {package}-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        f"{package}/__init__.py",
        f"{package}/mod.py",
        f"{package}_dist-1.0.dist-info/METADATA",
        f"{package}_dist-1.0.dist-info/RECORD",
    )
    with (meta / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    return importlib.metadata.Distribution.at(meta)


def _populate(
    tmp_path: Path, package: str, module_source: str, export: str, consumer: str
):
    dist = _distribution(tmp_path, package, module_source, export)
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction(
        workspace_root=str(tmp_path)
    )
    tree = SourceFile(
        workspace_path_source(str(path), root=str(tmp_path)),
        construction_context=context,
    )
    # Inject distribution index via authenticate path: populate uses
    # authenticate_dependency_top_level which reads installed packages.
    # For unit tests we rely on the package layout under tmp_path being
    # discoverable — same pattern as other source-call instruments.
    populate_source_visible_call_frames(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={package: dist},
    )
    return context, tree


_BROKEN_SIBLING_MODULE = (
    "def target_fn(x):\n"
    "    return x + 1\n"
    "\n"
    "class BrokenSibling:\n"
    "    def method(self, a, b):\n"
    "        # multi-op Compare — same family as numpy_ leg-site residual\n"
    "        return a < b < 3\n"
)


def test_target_with_broken_sibling_constructs_authenticated_frame(tmp_path: Path):
    """Broken sibling class in the same module must not erase target_fn frame."""
    context, tree = _populate(
        tmp_path,
        package="reach_pkg",
        module_source=_BROKEN_SIBLING_MODULE,
        export="target_fn",
        consumer=("from reach_pkg import target_fn\n" "result = target_fn(1)\n"),
    )
    call = next(
        node
        for node in tree.nodes()
        if isinstance(node, SourceCall)
        and getattr(node.func, "id", None) == "target_fn"
    )
    span = call.line_col_span()
    coordinate = SourceFragmentCoordinateV1(
        tree.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    ref = context.source_call_resolutions.get(coordinate)
    assert isinstance(
        ref, SourceCallPreconstructionRefV1
    ), f"expected authenticated frame for target_fn; got {type(ref).__name__}: {ref}"


def test_target_that_is_broken_class_stays_loud(tmp_path: Path):
    """When the authenticated target *is* the broken class, panic stays loud."""
    context, tree = _populate(
        tmp_path,
        package="reach_pkg2",
        module_source=_BROKEN_SIBLING_MODULE,
        export="BrokenSibling",
        consumer=("from reach_pkg2 import BrokenSibling\n" "obj = BrokenSibling()\n"),
    )
    call = next(
        node
        for node in tree.nodes()
        if isinstance(node, SourceCall)
        and getattr(node.func, "id", None) == "BrokenSibling"
    )
    span = call.line_col_span()
    coordinate = SourceFragmentCoordinateV1(
        tree.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    result = context.source_call_resolutions.get(coordinate)
    assert not isinstance(
        result, SourceCallPreconstructionRefV1
    ), "broken class target must not mint an authenticated frame"
    assert isinstance(result, SourceCallPreconstructionGapV1), type(result)
    # Body gap (Compare leg) or construction gap — never silent green.
    assert result.kind in {
        "source-body-gap",
        "force-floor",
        "call-target-export-unresolved",
        "artifact-resolution",
    }


def test_target_actually_reaching_broken_local_class_stays_loud(tmp_path: Path):
    """Local named call to a broken class is a real reach — construction stays loud."""
    module = (
        "class BrokenSibling:\n"
        "    def method(self, a, b):\n"
        "        return a < b < 3\n"
        "\n"
        "def target_fn(x):\n"
        "    return BrokenSibling()\n"
    )
    context, tree = _populate(
        tmp_path,
        package="reach_pkg3",
        module_source=module,
        export="target_fn",
        consumer=("from reach_pkg3 import target_fn\n" "result = target_fn(1)\n"),
    )
    call = next(
        node
        for node in tree.nodes()
        if isinstance(node, SourceCall)
        and getattr(node.func, "id", None) == "target_fn"
    )
    span = call.line_col_span()
    coordinate = SourceFragmentCoordinateV1(
        tree.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    result = context.source_call_resolutions.get(coordinate)
    # Target reaches BrokenSibling locally → constructor sugar panics → gap/raise.
    assert not isinstance(result, SourceCallPreconstructionRefV1), result
