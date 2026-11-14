# SPDX-License-Identifier: MIT OR Apache-2.0
"""Authenticated dependency artifact graphs.

The graph authenticates installed bytes only.  It never answers what an
imported name is: that is the import table's target symbol and the imported
proofs in ``.sugar/imports/`` (step 3).
"""

from __future__ import annotations

import csv
from dataclasses import replace
import importlib.metadata
from pathlib import Path
import sys
from types import MappingProxyType

import pytest

from sugar_lift_python_source import dependency_artifact
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactAuthenticationError,
    DependencyArtifactGraph,
    AuthenticatedModuleSourceV1,
)


def _install_distribution(
    root: Path, *, package_source: str, implementation_source: str
) -> importlib.metadata.Distribution:
    package = root / "example_pkg"
    package.mkdir()
    (package / "__init__.py").write_text(package_source, encoding="utf-8")
    (package / "implementation.py").write_text(implementation_source, encoding="utf-8")
    metadata = root / "example_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: example-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text("example_pkg\n", encoding="utf-8")
    recorded = (
        "example_pkg/__init__.py",
        "example_pkg/implementation.py",
        "example_dist-1.0.dist-info/METADATA",
        "example_dist-1.0.dist-info/top_level.txt",
        "example_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for path in recorded:
            writer.writerow((path, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def test_the_graph_has_no_export_resolution_door() -> None:
    # Step 3: an imported name is answered only by the imported proofs.  The
    # dependency-source export readers are gone, not hidden.
    for name in (
        "resolve_import_binding",
        "resolve_authenticated_module_export",
        "export_statement_coverage",
        "ResolvedPythonObjectV1",
        "PythonObjectResolutionGapV1",
    ):
        assert not hasattr(dependency_artifact, name), name


def test_same_spelled_non_stdlib_module_cannot_mint_stdlib_graph(
    tmp_path: Path,
) -> None:
    impostor = tmp_path / "contextlib.py"
    impostor.write_text("class suppress:\n    pass\n", encoding="utf-8")

    with pytest.raises(
        DependencyArtifactAuthenticationError, match="authenticated stdlib root"
    ):
        DependencyArtifactGraph.authenticate_stdlib_path(
            "contextlib", impostor, stdlib_root=Path(sys.base_prefix) / "lib"
        )


def test_any_source_visible_stdlib_module_uses_the_same_graph_intake() -> None:
    graph = DependencyArtifactGraph.authenticate_stdlib_module("typing")

    assert graph.artifact_kind == "stdlib"
    assert "typing" in graph.modules
    assert graph.distribution_artifact_cid.startswith("blake3-512:")


def test_fabricated_artifact_file_wrapper_is_loud(tmp_path: Path) -> None:
    graph = DependencyArtifactGraph.authenticate(
        _install_distribution(
            tmp_path,
            package_source="from example_pkg.implementation import build\n",
            implementation_source="def build(value):\n    return value\n",
        )
    )

    with pytest.raises(DependencyArtifactAuthenticationError):
        replace(graph.files[0], content=b"forged bytes")


def test_recorded_source_seat_cannot_be_relabelled_as_invented_module(
    tmp_path: Path,
) -> None:
    graph = DependencyArtifactGraph.authenticate(
        _install_distribution(
            tmp_path,
            package_source="from example_pkg.implementation import build\n",
            implementation_source="def build(value):\n    return value\n",
        )
    )
    real = graph.modules["example_pkg.implementation"]
    invented = AuthenticatedModuleSourceV1(
        module_name="invented.module",
        source_seat=real.source_seat,
        source_cid=real.source_cid,
        source=real.source,
    )

    with pytest.raises(
        DependencyArtifactAuthenticationError,
        match="cannot be allocated from graph fields",
    ):
        replace(graph, modules=MappingProxyType({"invented.module": invented}))
