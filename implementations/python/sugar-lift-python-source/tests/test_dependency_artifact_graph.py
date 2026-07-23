# SPDX-License-Identifier: MIT OR Apache-2.0
from __future__ import annotations

import csv
from dataclasses import replace
import importlib.metadata
import json
from pathlib import Path
import sys

import pytest

from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactAuthenticationError,
    DependencyArtifactGraph,
    PythonObjectResolutionGapV1,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.canonical import blake3_512_of


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


def _demand(
    root: Path, source: str = "import example_pkg\nexample_pkg.build(1)\n"
) -> dict[str, object]:
    from sugar_lift_py_tests.import_binding import authenticated_import_uses

    path = root / "consumer.py"
    path.write_text(source, encoding="utf-8")
    source_cid = blake3_512_of(source.encode("utf-8"))
    rows, outcomes = authenticated_import_uses(
        root, path, source, source_cid, module_identities={}
    )
    assert set(outcomes.values()) == {"authenticated-import-use"}
    return next(item for item in rows if item["kind"] == "call-contract-demand")


def test_static_reexport_resolves_to_content_addressed_definition_without_import(
    tmp_path: Path,
) -> None:
    distribution = _install_distribution(
        tmp_path,
        package_source=(
            "from example_pkg.implementation import build\n"
            "raise RuntimeError('module execution is forbidden')\n"
        ),
        implementation_source="def build(value):\n    return value\n",
    )
    sys.modules.pop("example_pkg", None)
    sys.modules.pop("example_pkg.implementation", None)

    graph = DependencyArtifactGraph.authenticate(distribution)
    demand = _demand(tmp_path)
    result = resolve_import_binding(
        demand["importBinding"], target_symbol=demand["targetSymbol"], graph=graph
    )

    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.distribution_artifact_cid == graph.distribution_artifact_cid
    assert result.module_name == "example_pkg.implementation"
    assert result.source_cid == graph.modules[result.module_name].source_cid
    assert result.definition.kind == "function"
    assert result.definition.name == "build"
    assert result.definition.source_cid == result.source_cid
    assert len(result.reexport_warrants) == 1
    assert result.reexport_warrants[0].from_module == "example_pkg"
    assert result.reexport_warrants[0].to_module == "example_pkg.implementation"
    assert result.cid.startswith("blake3-512:")
    assert "example_pkg" not in sys.modules
    assert "example_pkg.implementation" not in sys.modules


def test_resolved_python_object_round_trips_with_identical_cid(tmp_path: Path) -> None:
    distribution = _install_distribution(
        tmp_path,
        package_source="from example_pkg.implementation import build\n",
        implementation_source="class build:\n    pass\n",
    )
    graph = DependencyArtifactGraph.authenticate(distribution)
    demand = _demand(tmp_path, "from example_pkg import build as make\nmake(1)\n")
    result = resolve_import_binding(
        demand["importBinding"], target_symbol=demand["targetSymbol"], graph=graph
    )
    assert isinstance(result, ResolvedPythonObjectV1)

    encoded = json.loads(json.dumps(result.to_value(), sort_keys=True))
    decoded = ResolvedPythonObjectV1.from_value(encoded)

    assert decoded == result
    assert decoded.cid == result.cid
    assert decoded.definition.kind == "class"


def test_dynamic_export_stays_a_typed_loud_gap(tmp_path: Path) -> None:
    distribution = _install_distribution(
        tmp_path,
        package_source=("def __getattr__(name):\n" "    return object()\n"),
        implementation_source="def build(value):\n    return value\n",
    )
    graph = DependencyArtifactGraph.authenticate(distribution)

    demand = _demand(tmp_path)
    result = resolve_import_binding(
        demand["importBinding"], target_symbol=demand["targetSymbol"], graph=graph
    )

    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"
    assert result.import_binding_cid.startswith("blake3-512:")
    assert result.distribution_artifact_cid == graph.distribution_artifact_cid


def test_real_pytest_reexport_resolves_without_manager_name_recognition(
    tmp_path: Path,
) -> None:
    graph = DependencyArtifactGraph.authenticate(
        importlib.metadata.distribution("pytest")
    )
    demand = _demand(tmp_path, "import pytest\npytest.raises(ValueError)\n")

    result = resolve_import_binding(
        demand["importBinding"], target_symbol=demand["targetSymbol"], graph=graph
    )

    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.definition.name == "raises"
    assert result.definition.kind == "function"
    assert result.module_name != "pytest"
    assert result.reexport_warrants
    assert result.definition.source_cid == result.source_cid


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
