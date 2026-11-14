"""Re-export: reaching alias, target-module star publication, Completed fall-through.

- Alias follows the RHS binding *reaching* the assignment, not the RHS final bind.
- Star publication is the *target* module's ``__all__`` / public-name rule.
- Prefix licenses a binding only via reduce → one unconditional
  ``Completed(can_fall_through=True)`` (not AST control admission).
"""

from __future__ import annotations

import ast
import csv
import importlib.metadata
from pathlib import Path
from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    PythonObjectResolutionGapV1,
    ResolvedPythonObjectV1,
    resolve_import_binding as _resolve_import_binding,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession


def resolve_import_binding(*args, graph, session=None, **kwargs):
    """This file's authenticated graph is the distribution under test."""
    if session is None:
        name = graph.distribution_name
        if not name:
            raise AssertionError("re-export graph test requires a distribution name")
        session = SourceResolutionSession(enrolled_distributions=frozenset({name}))
    return _resolve_import_binding(*args, graph=graph, session=session, **kwargs)


def _dist(
    root: Path, *, name: str, files: dict[str, str]
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
            "cyc_pkg/__init__.py": ("_a = _b\n" "_b = _a\n" "build = _a\n"),
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
                "from all_pkg.implementation import *\n" '__all__ = ["not_build"]\n'
            ),
            "all_pkg/implementation.py": (
                "def build(value):\n    return value\n" '__all__ = ["build"]\n'
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
                "def build(value):\n    return value\n" '__all__ = ["other"]\n'
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


def test_nested_literal_all_stays_dynamic(tmp_path: Path) -> None:
    """A nested ``__all__`` is not module-body publication testimony."""
    dist = _dist(
        tmp_path,
        name="nested-all-pkg",
        files={
            "nested_all_pkg/__init__.py": "from nested_all_pkg.implementation import *\n",
            "nested_all_pkg/implementation.py": (
                "def build(value):\n    return value\n"
                "if flag:\n"
                "    __all__ = ['build']\n"
            ),
        },
    )
    result = resolve_import_binding(
        _call_demand(tmp_path, "import nested_all_pkg\nnested_all_pkg.build(1)\n"),
        graph=DependencyArtifactGraph.authenticate(dist),
    )
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"


def test_two_star_imports_are_ambiguous(tmp_path: Path) -> None:
    """Two star producers cannot overwrite one another's authority."""
    dist = _dist(
        tmp_path,
        name="two-star-pkg",
        files={
            "two_star_pkg/__init__.py": (
                "from two_star_pkg.first import *\n"
                "from two_star_pkg.second import *\n"
            ),
            "two_star_pkg/first.py": "def build(value):\n    return value\n",
            "two_star_pkg/second.py": "def build(value):\n    return value + 1\n",
        },
    )
    result = resolve_import_binding(
        _call_demand(tmp_path, "import two_star_pkg\ntwo_star_pkg.build(1)\n"),
        graph=DependencyArtifactGraph.authenticate(dist),
    )
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "ambiguous-static-export"


def test_nested_alias_locus_refuses_without_suite_reconstruction(
    tmp_path: Path,
) -> None:
    """An inner-suite alias cannot borrow module-body reaching authority."""
    dist = _dist(
        tmp_path,
        name="nested-alias-pkg",
        files={
            "nested_alias_pkg/__init__.py": (
                "from nested_alias_pkg.implementation import build as _build\n"
                "if flag:\n"
                "    build = _build\n"
            ),
            "nested_alias_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    result = resolve_import_binding(
        _call_demand(tmp_path, "import nested_alias_pkg\nnested_alias_pkg.build(1)\n"),
        graph=DependencyArtifactGraph.authenticate(dist),
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
                "assert False\n" "from assert_pkg.implementation import build\n"
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
                "pass\n" "from ok_pkg.implementation import build\n"
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


def test_empty_prefix_licenses_first_statement_definition(tmp_path: Path) -> None:
    """Five-step: empty prefix (bind is first stmt) is vacuous Completed."""
    dist = _dist(
        tmp_path,
        name="first-pkg",
        files={
            "first_pkg/__init__.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import first_pkg\nfirst_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.module_name == "first_pkg"
    assert result.definition.name == "build"


def test_prefix_equal_multi_face_if_preserves_completed_fallthrough(
    tmp_path: Path,
) -> None:
    """Two unresolved faces with the same state still prove fallthrough."""
    dist = _dist(
        tmp_path,
        name="face-pkg",
        files={
            "face_pkg/__init__.py": (
                "flag = unknown\n"
                "if flag:\n"
                "    pass\n"
                "else:\n"
                "    pass\n"
                "from face_pkg.implementation import build\n"
            ),
            "face_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import face_pkg\nface_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, ResolvedPythonObjectV1)


def test_prefix_branch_owned_export_stays_named_dynamic(tmp_path: Path) -> None:
    """A binding owned by only one unresolved face is never promoted."""
    dist = _dist(
        tmp_path,
        name="branch-face-pkg",
        files={
            "branch_face_pkg/__init__.py": (
                "flag = unknown\n"
                "if flag:\n"
                "    from branch_face_pkg.implementation import build\n"
                "else:\n"
                "    pass\n"
            ),
            "branch_face_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import branch_face_pkg\nbranch_face_pkg.build(1)\n"),
        graph=graph,
    )

    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"


def test_prefix_does_not_include_the_binding_statement_itself(tmp_path: Path) -> None:
    """Statements *before* the locus only: a raise *at* the bind is not prefix."""
    # Raise is the first (and binding) statement on a dynamic path; empty
    # prefix for a pure definition after pass is licensed separately above.
    dist = _dist(
        tmp_path,
        name="bind-only-pkg",
        files={
            "bind_only_pkg/__init__.py": (
                "from bind_only_pkg.implementation import build\n"
            ),
            "bind_only_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    result = resolve_import_binding(
        _call_demand(tmp_path, "import bind_only_pkg\nbind_only_pkg.build(1)\n"),
        graph=graph,
    )
    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.module_name == "bind_only_pkg.implementation"


def test_competing_static_binds_stay_ambiguous(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="amb-pkg",
        files={
            "amb_pkg/__init__.py": (
                "flag = unknown\n"
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
                "def __getattr__(name):\n" "    raise AttributeError(name)\n"
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


def test_decided_if_takes_the_live_arm(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="live-if-pkg",
        files={
            "live_if_pkg/__init__.py": (
                "flag = True\n"
                "if flag:\n"
                "    from live_if_pkg.implementation import build\n"
                "else:\n"
                "    def build(value):\n"
                "        return value + 1\n"
            ),
            "live_if_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    result = resolve_import_binding(
        _call_demand(tmp_path, "import live_if_pkg\nlive_if_pkg.build(1)\n"),
        graph=DependencyArtifactGraph.authenticate(dist),
    )
    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.module_name == "live_if_pkg.implementation"
    assert result.definition.name == "build"


def test_nameerror_default_takes_the_else_arm(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="setup-pkg",
        files={
            "setup_pkg/__init__.py": (
                "try:\n"
                "    __SETUP__\n"
                "except NameError:\n"
                "    __SETUP__ = False\n"
                "if __SETUP__:\n"
                "    def build(value):\n"
                "        return 'setup'\n"
                "else:\n"
                "    from setup_pkg.implementation import build\n"
            ),
            "setup_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    result = resolve_import_binding(
        _call_demand(tmp_path, "import setup_pkg\nsetup_pkg.build(1)\n"),
        graph=DependencyArtifactGraph.authenticate(dist),
    )
    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.module_name == "setup_pkg.implementation"


def test_prebound_setup_flag_keeps_the_setup_arm(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="prebound-setup-pkg",
        files={
            "prebound_setup_pkg/__init__.py": (
                "__SETUP__ = True\n"
                "try:\n"
                "    __SETUP__\n"
                "except NameError:\n"
                "    __SETUP__ = False\n"
                "if __SETUP__:\n"
                "    def build(value):\n"
                "        return 'setup'\n"
                "else:\n"
                "    from prebound_setup_pkg.implementation import build\n"
            ),
            "prebound_setup_pkg/implementation.py": "def build(value):\n    return value\n",
        },
    )
    result = resolve_import_binding(
        _call_demand(tmp_path, "import prebound_setup_pkg\nprebound_setup_pkg.build(1)\n"),
        graph=DependencyArtifactGraph.authenticate(dist),
    )
    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.module_name == "prebound_setup_pkg"
    assert result.definition.name == "build"


def test_two_stars_one_publisher_resolves(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="one-star-pkg",
        files={
            "one_star_pkg/__init__.py": (
                "from one_star_pkg.first import *\n"
                "from one_star_pkg.second import *\n"
            ),
            "one_star_pkg/first.py": (
                "def build(value):\n    return value\n"
                "__all__ = ['build']\n"
            ),
            "one_star_pkg/second.py": (
                "def other(value):\n    return value\n"
                "__all__ = ['other']\n"
            ),
        },
    )
    result = resolve_import_binding(
        _call_demand(tmp_path, "import one_star_pkg\none_star_pkg.build(1)\n"),
        graph=DependencyArtifactGraph.authenticate(dist),
    )
    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.module_name == "one_star_pkg.first"


def test_all_extended_from_another_module_publishes(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="extend-all-pkg",
        files={
            "extend_all_pkg/__init__.py": (
                "from . import source\n"
                "from .source import *\n"
                "__all__ = []\n"
                "__all__ += source.__all__\n"
            ),
            "extend_all_pkg/source.py": (
                "def build(value):\n    return value\n"
                "__all__ = ['build']\n"
            ),
        },
    )
    result = resolve_import_binding(
        _call_demand(tmp_path, "import extend_all_pkg\nextend_all_pkg.build(1)\n"),
        graph=DependencyArtifactGraph.authenticate(dist),
    )
    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.module_name == "extend_all_pkg.source"


def test_extend_all_helper_unions_target_all(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="helper-all-pkg",
        files={
            "helper_all_pkg/__init__.py": (
                "from . import source\n"
                "from .source import *\n"
                "__all__ = []\n"
                "def extend_all(module):\n"
                "    existing = set(__all__)\n"
                "    mall = module.__all__\n"
                "    for a in mall:\n"
                "        if a not in existing:\n"
                "            __all__.append(a)\n"
                "extend_all(source)\n"
            ),
            "helper_all_pkg/source.py": (
                "class Resource:\n"
                "    def __enter__(self):\n"
                "        return self\n"
                "    def __exit__(self, *exc):\n"
                "        pass\n"
                "__all__ = ['Resource']\n"
            ),
        },
    )
    result = resolve_import_binding(
        _call_demand(tmp_path, "import helper_all_pkg\nhelper_all_pkg.Resource()\n"),
        graph=DependencyArtifactGraph.authenticate(dist),
    )
    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.module_name == "helper_all_pkg.source"
    assert result.definition.name == "Resource"


def test_named_extend_all_that_does_more_stays_dynamic(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="lying-helper-pkg",
        files={
            "lying_helper_pkg/__init__.py": "from lying_helper_pkg.child import *\n",
            "lying_helper_pkg/child.py": (
                "from . import source\n"
                "__all__ = []\n"
                "def extend_all(module):\n"
                "    __all__.append('build')\n"
                "extend_all(source)\n"
            ),
            "lying_helper_pkg/source.py": (
                "def build(value):\n    return value\n"
                "__all__ = ['build']\n"
            ),
        },
    )
    result = resolve_import_binding(
        _call_demand(tmp_path, "import lying_helper_pkg\nlying_helper_pkg.build(1)\n"),
        graph=DependencyArtifactGraph.authenticate(dist),
    )
    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"


def test_prefix_try_abort_and_finite_for_still_resolves(tmp_path: Path) -> None:
    dist = _dist(
        tmp_path,
        name="abort-prefix-pkg",
        files={
            "abort_prefix_pkg/__init__.py": (
                "import os\n"
                "env_added = []\n"
                "for key in ['OPENBLAS_MAIN_FREE']:\n"
                "    if key not in os.environ:\n"
                "        env_added.append(key)\n"
                "try:\n"
                "    from . import sibling\n"
                "except ImportError:\n"
                "    raise\n"
                "finally:\n"
                "    for key in env_added:\n"
                "        pass\n"
                "from .sibling import helper\n"
            ),
            "abort_prefix_pkg/sibling.py": "def helper():\n    return 1\n",
        },
    )
    result = resolve_import_binding(
        _call_demand(tmp_path, "import abort_prefix_pkg\nabort_prefix_pkg.helper()\n"),
        graph=DependencyArtifactGraph.authenticate(dist),
    )
    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.module_name == "abort_prefix_pkg.sibling"
    assert result.definition.name == "helper"


def test_while_true_prefix_does_not_license_a_later_bind() -> None:
    from sugar_lift_python_source.dependency_export_adapter import (
        _prefix_reaches_locus_or_aborts,
    )

    tree = ast.parse("while True:\n    pass\ndef helper():\n    return 1\n")
    assert _prefix_reaches_locus_or_aborts(tree.body, tree.body[1]) is False
