"""Re-export: reaching alias, target-module star publication, Completed fall-through.

- Alias follows the RHS binding *reaching* the assignment, not the RHS final bind.
- Star publication is the *target* module's ``__all__`` / public-name rule.
- Prefix licenses a binding only via reduce → one unconditional
  ``Completed(can_fall_through=True)`` (not AST control admission).
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    PythonObjectResolutionGapV1,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)


def _dist(root: Path, *, name: str, files: dict[str, str]) -> importlib.metadata.Distribution:
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
    recorded = (
        *files.keys(),
        f"{meta.name}/METADATA",
        f"{meta.name}/top_level.txt",
        f"{meta.name}/RECORD",
    )
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


def test_direct_reexport_still_resolves(tmp_path: Path) -> None:
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
    assert len(result.reexport_warrants) == 1
    assert result.reexport_warrants[0].definition.kind == "import"


def test_chained_reexport_still_resolves(tmp_path: Path) -> None:
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
    assert len(result.reexport_warrants) == 2


def test_static_alias_records_both_occurrences(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="alias-pkg",
        files={
            "alias_pkg/__init__.py": (
                "from alias_pkg.implementation import build as _build\n"
                "build = _build\n"
            ),
            "alias_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import alias_pkg\nalias_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.definition.name == "build"
    assert result.module_name == "alias_pkg.implementation"
    assert len(result.reexport_warrants) == 2
    alias_w, import_w = result.reexport_warrants
    assert alias_w.definition.kind == "alias"
    assert alias_w.exported_name == "build"
    assert alias_w.imported_name == "_build"
    assert alias_w.from_module == alias_w.to_module == "alias_pkg"
    assert import_w.definition.kind == "import"
    assert import_w.to_module == "alias_pkg.implementation"


def test_alias_follows_reaching_rhs_not_final_rhs_binding(tmp_path: Path) -> None:
    """After ``public = _f``, rebinding ``_f`` must not change ``public``'s target."""
    dist = _dist(
        tmp_path,
        name="reach-pkg",
        files={
            "reach_pkg/__init__.py": (
                "from reach_pkg.implementation import build as _build\n"
                "build = _build\n"
                "_build = None\n"
            ),
            "reach_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import reach_pkg\nreach_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, ResolvedPythonObjectV1), getattr(result, "kind", result)
    assert result.module_name == "reach_pkg.implementation"
    assert result.definition.name == "build"


def test_public_name_reassignment_stays_dynamic(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="re-pkg",
        files={
            "re_pkg/__init__.py": (
                "from re_pkg.implementation import build as _build\n"
                "build = _build\n"
                "build = None\n"
            ),
            "re_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import re_pkg\nre_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"


def test_alias_cycle_stays_gapped(tmp_path: Path) -> None:
    """Mutual aliases without an import foundation cannot resolve."""
    dist = _dist(
        tmp_path,
        name="cyc-pkg",
        files={
            "cyc_pkg/__init__.py": (
                "_a = _b\n"
                "_b = _a\n"
                "build = _a\n"
            ),
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import cyc_pkg\ncyc_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind in {
        "reexport-cycle",
        "dynamic-export",
        "static-export-absent",
    }


def test_computed_alias_stays_dynamic(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="cmp-pkg",
        files={
            "cmp_pkg/__init__.py": (
                "from cmp_pkg.implementation import build as _build\n"
                "build = _build if True else _build\n"
            ),
            "cmp_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import cmp_pkg\ncmp_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"


def test_wildcard_without_all_uses_target_public_names(tmp_path: Path) -> None:
    """No ``__all__`` on target → public (non-``_``) names only."""
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
    assert isinstance(result, ResolvedPythonObjectV1), getattr(result, "kind", result)
    assert result.module_name == "star_pkg.implementation"


def test_star_uses_target_module_all_not_importer(tmp_path: Path) -> None:
    """Importer ``__all__`` does not control star; target module's rule does."""
    dist = _dist(
        tmp_path,
        name="all-pkg",
        files={
            # Importer lists a red herring; target is the authority.
            "all_pkg/__init__.py": (
                "from all_pkg.implementation import *\n"
                '__all__ = ["not_build"]\n'
            ),
            "all_pkg/implementation.py": (
                "def build(value):\n    return value\n"
                '__all__ = ["build"]\n'
            ),
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import all_pkg\nall_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, ResolvedPythonObjectV1), getattr(result, "kind", result)
    assert result.definition.name == "build"
    assert result.module_name == "all_pkg.implementation"


def test_star_target_all_excludes_name_stays_dynamic(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="miss-pkg",
        files={
            "miss_pkg/__init__.py": "from miss_pkg.implementation import *\n",
            "miss_pkg/implementation.py": (
                "def build(value):\n    return value\n"
                '__all__ = ["other"]\n'
            ),
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import miss_pkg\nmiss_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"


def test_star_target_public_name_without_all(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="pub-pkg",
        files={
            "pub_pkg/__init__.py": "from pub_pkg.implementation import *\n",
            "pub_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import pub_pkg\npub_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, ResolvedPythonObjectV1), getattr(result, "kind", result)
    assert result.module_name == "pub_pkg.implementation"


def test_star_target_private_name_without_all_stays_dynamic(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="priv-pkg",
        files={
            "priv_pkg/__init__.py": "from priv_pkg.implementation import *\n",
            "priv_pkg/implementation.py": "def _build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    # Demand the private name via star — not in public set without __all__.
    result = resolve_import_binding(
        _call_demand(tmp_path, "import priv_pkg\npriv_pkg._build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"


def test_computed_target_all_stays_dynamic(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="comp-all-pkg",
        files={
            "comp_all_pkg/__init__.py": "from comp_all_pkg.implementation import *\n",
            "comp_all_pkg/implementation.py": (
                "def build(value):\n    return value\n"
                'names = ["build"]\n'
                "__all__ = names\n"
            ),
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import comp_all_pkg\ncomp_all_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"


def test_prefix_raise_refuses_binding_via_completed_fallthrough(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="raise-pkg",
        files={
            "raise_pkg/__init__.py": (
                "raise RuntimeError('abort')\n"
                "from raise_pkg.implementation import build\n"
            ),
            "raise_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import raise_pkg\nraise_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"


def test_prefix_assert_false_refuses_binding(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="assert-pkg",
        files={
            "assert_pkg/__init__.py": (
                "assert False\n"
                "from assert_pkg.implementation import build\n"
            ),
            "assert_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import assert_pkg\nassert_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"


def test_prefix_pass_licenses_binding(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="ok-pkg",
        files={
            "ok_pkg/__init__.py": (
                "pass\n"
                "from ok_pkg.implementation import build\n"
            ),
            "ok_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import ok_pkg\nok_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.module_name == "ok_pkg.implementation"


def test_competing_static_binds_stay_ambiguous(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="amb-pkg",
        files={
            "amb_pkg/__init__.py": (
                "flag = True\n"
                "if flag:\n"
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


def test_getattr_stays_dynamic(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="dyn-pkg",
        files={
            "dyn_pkg/__init__.py": (
                "def __getattr__(name):\n"
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
