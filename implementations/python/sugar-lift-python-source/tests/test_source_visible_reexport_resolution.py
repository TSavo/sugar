"""Source-visible re-export resolution — general chain, no spelling admission.

Acceptance: authenticated import binding → source-visible re-export hop(s) →
exact exported object coordinate (definition CID).  Twins pin direct and
chained resolve; tampered source/CID refuse; competing definitions stay
ambiguous; ``__getattr__``, wildcard-only, and genuinely dynamic stay
``dynamic-export``.  No pandas.array spelling, module admission list,
first-candidate, or filesystem scan in production.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    PythonObjectResolutionGapV1,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)


def _dist(
    root: Path,
    *,
    name: str,
    files: dict[str, str],
) -> importlib.metadata.Distribution:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    meta = root / f"{name.replace('-', '_')}_dist-1.0.dist-info"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n",
        encoding="utf-8",
    )
    top = next(iter(files)).split("/", 1)[0]
    (meta / "top_level.txt").write_text(f"{top}\n", encoding="utf-8")
    recorded = (*files.keys(), f"{meta.name}/METADATA", f"{meta.name}/top_level.txt", f"{meta.name}/RECORD")
    with (meta / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    return importlib.metadata.Distribution.at(meta)


def _call_demand(root: Path, source: str):
    path = root / "consumer.py"
    path.write_text(source, encoding="utf-8")
    source_cid = blake3_512_of(source.encode("utf-8"))
    receipts, _ = authenticated_import_use_receipts(
        root, path, source, source_cid, module_identities={}
    )
    assert len(receipts) == 1
    return receipts[0]


def test_direct_reexport_resolves_to_definition_coordinate(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="example-pkg",
        files={
            "example_pkg/__init__.py": "from example_pkg.implementation import build\n",
            "example_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import example_pkg\nexample_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.module_name == "example_pkg.implementation"
    assert result.definition.name == "build"
    assert result.definition.kind == "function"
    assert result.definition.source_cid == result.source_cid
    assert len(result.reexport_warrants) == 1
    assert result.reexport_warrants[0].from_module == "example_pkg"
    assert result.reexport_warrants[0].to_module == "example_pkg.implementation"


def test_chained_reexport_resolves_with_per_hop_testimony(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="example-pkg",
        files={
            "example_pkg/__init__.py": "from example_pkg.mid import build\n",
            "example_pkg/mid.py": "from example_pkg.implementation import build\n",
            "example_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import example_pkg\nexample_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.module_name == "example_pkg.implementation"
    assert result.definition.name == "build"
    assert len(result.reexport_warrants) == 2
    assert result.reexport_warrants[0].from_module == "example_pkg"
    assert result.reexport_warrants[0].to_module == "example_pkg.mid"
    assert result.reexport_warrants[1].from_module == "example_pkg.mid"
    assert result.reexport_warrants[1].to_module == "example_pkg.implementation"
    # Per-hop source CIDs are the authenticated module seats, not spellings.
    assert (
        result.reexport_warrants[0].from_source_cid
        == graph.modules["example_pkg"].source_cid
    )
    assert (
        result.reexport_warrants[0].to_source_cid
        == graph.modules["example_pkg.mid"].source_cid
    )
    assert (
        result.reexport_warrants[1].to_source_cid
        == graph.modules["example_pkg.implementation"].source_cid
    )


def test_tampered_binding_source_cid_refuses(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="example-pkg",
        files={
            "example_pkg/__init__.py": "from example_pkg.implementation import build\n",
            "example_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    path = tmp_path / "tamper_consumer.py"
    source = "import example_pkg\nexample_pkg.build(1)\n"
    path.write_text(source, encoding="utf-8")
    source_cid = blake3_512_of(source.encode("utf-8"))
    lying_module_cid = "blake3-512:" + "0" * 128
    assert lying_module_cid != graph.modules["example_pkg"].source_cid
    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts

    receipts, _ = authenticated_import_use_receipts(
        tmp_path,
        path,
        source,
        source_cid,
        module_identities={
            "example_pkg": {
                "kind": "authenticated-python-module",
                "moduleName": "example_pkg",
                "sourceCid": lying_module_cid,
            }
        },
    )
    assert len(receipts) == 1
    result = resolve_import_binding(receipts[0], graph=graph)
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "opaque-source"


def test_competing_definitions_stay_ambiguous(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="amb-pkg",
        files={
            "amb_pkg/__init__.py": (
                "if True:\n"
                "    def build(value):\n"
                "        return value\n"
                "else:\n"
                "    def build(value):\n"
                "        return value\n"
            ),
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import amb_pkg\namb_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "ambiguous-static-export"


def test_getattr_served_export_stays_dynamic(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="dyn-pkg",
        files={
            "dyn_pkg/__init__.py": (
                "def __getattr__(name):\n"
                "    if name == 'build':\n"
                "        def build(value):\n"
                "            return value\n"
                "        return build\n"
                "    raise AttributeError(name)\n"
            ),
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import dyn_pkg\ndyn_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"


def test_wildcard_only_export_stays_dynamic(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="star-pkg",
        files={
            "star_pkg/__init__.py": "from star_pkg.implementation import *\n",
            "star_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import star_pkg\nstar_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"


def test_genuinely_dynamic_assignment_stays_dynamic(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="assign-pkg",
        files={
            "assign_pkg/__init__.py": "build = (lambda value: value)\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import assign_pkg\nassign_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"


def test_hard_abort_raise_before_source_visible_reexport_still_resolves(
    tmp_path: Path,
) -> None:
    """Dependency-check raises that abort module init do not poison later imports.

    Success path is the residual suite; only suppressible With prefixes stay dynamic.
    """
    dist = _dist(
        tmp_path,
        name="gate-pkg",
        files={
            "gate_pkg/__init__.py": (
                "for _missing in ():\n"
                "    raise ImportError('missing dep')\n"
                "from gate_pkg.implementation import build\n"
            ),
            "gate_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import gate_pkg\ngate_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.definition.name == "build"
    assert result.module_name == "gate_pkg.implementation"


def test_with_suppressible_raise_still_refuses_unreachable_export(
    tmp_path: Path,
) -> None:
    """Preserved: With that can swallow a raise must not authenticate a later bind."""
    dist = _dist(
        tmp_path,
        name="with-pkg",
        files={
            "with_pkg/__init__.py": "from with_pkg.implementation import build\n",
            "with_pkg/implementation.py": (
                "def build(value):\n    return 'old'\n"
                "with suppresses_exceptions():\n"
                "    raise RuntimeError()\n"
                "    def build(value):\n        return 'new'\n"
            ),
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import with_pkg\nwith_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"
