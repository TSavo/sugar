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
    resolve_import_binding,
)


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


def test_module_prefix_execution_binds_exact_class_definition_once(
    tmp_path: Path,
) -> None:
    """Module definition execution retains the class Floor for later loads.

    This is the producer boundary needed by authenticated module prefixes: a
    later statement must consume the exact class constructed by the earlier
    ClassDef, rather than seeing a reconstructed SymbolicValue with the same
    name.
    """
    from sugar_lift_py_tests.floor import ClassDefinitionValue
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_python_source import manager_construction

    source = (
        "class Boundary:\n"
        "    FIRST = 1\n"
        "    SECOND = 2\n"
        "alias = Boundary\n"
        "def build():\n"
        "    return alias\n"
    )
    dist = _dist(
        tmp_path,
        name="module-definition-prefix-pkg",
        files={"module_definition_prefix_pkg/__init__.py": source},
    )
    module = DependencyArtifactGraph.authenticate(dist).modules[
        "module_definition_prefix_pkg"
    ]
    locus = ast.parse(source).body[-1]

    exits = manager_construction._module_prefix_outcome(module, locus)

    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    boundary = completed.value.context.temporal.value_if_bound("Boundary")
    assert type(boundary) is ClassDefinitionValue
    assert tuple(field.name for field in boundary.class_fields) == (
        "FIRST",
        "SECOND",
    )


def test_module_prefix_defers_forward_function_body_until_prefix_temporal_is_live(
    tmp_path: Path,
) -> None:
    """Construction does not execute a forward function without prefix state."""
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_python_source import manager_construction

    source = (
        "registry: dict[str, int] = {}\n"
        "def caller(key):\n"
        "    return lookup(key)\n"
        "def lookup(key):\n"
        "    return registry[key]\n"
        "def build():\n"
        "    return caller\n"
    )
    dist = _dist(
        tmp_path,
        name="module-local-call-prefix-pkg",
        files={"module_local_call_prefix_pkg/__init__.py": source},
    )
    module = DependencyArtifactGraph.authenticate(dist).modules[
        "module_local_call_prefix_pkg"
    ]

    exits = manager_construction._module_prefix_outcome(
        module, ast.parse(source).body[-1]
    )

    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    caller = completed.value.context.temporal.value_if_bound("caller")
    assert type(caller).__name__ == "_ModuleFunctionDefinitionCallableV1"
    assert caller.definition.name == "caller"


def test_module_prefix_does_not_construct_an_uncalled_function_body(
    tmp_path: Path,
) -> None:
    """Publishing a FunctionDef retains its body until authenticated application."""
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_python_source import manager_construction

    source = (
        "def dormant(manager):\n"
        "    with manager:\n"
        "        return 1\n"
        "def build():\n"
        "    return 2\n"
    )
    dist = _dist(
        tmp_path,
        name="lazy-module-function-pkg",
        files={"lazy_module_function_pkg/__init__.py": source},
    )
    module = DependencyArtifactGraph.authenticate(dist).modules[
        "lazy_module_function_pkg"
    ]

    exits = manager_construction._module_prefix_outcome(
        module, ast.parse(source).body[-1]
    )

    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    dormant = completed.value.context.temporal.value_if_bound("dormant")
    assert type(dormant) is manager_construction._ModuleFunctionDefinitionCallableV1
    assert dormant.definition.name == "dormant"


def test_module_prefix_publishes_exact_async_definition_without_running_body(
    tmp_path: Path,
) -> None:
    """An authenticated async definition binds its exact parser-owned occurrence."""
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_python_source import manager_construction
    from sugar_source_tree.nodes import AsyncFunctionDef

    source = (
        "async def dormant(manager):\n"
        "    with manager:\n"
        "        return 1\n"
        "def build():\n"
        "    return dormant\n"
    )
    dist = _dist(
        tmp_path,
        name="async-module-function-pkg",
        files={"async_module_function_pkg/__init__.py": source},
    )
    module = DependencyArtifactGraph.authenticate(dist).modules[
        "async_module_function_pkg"
    ]

    exits = manager_construction._module_prefix_outcome(
        module, ast.parse(source).body[-1]
    )

    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    dormant = completed.value.context.temporal.value_if_bound("dormant")
    assert type(dormant).__name__ == "_ModuleFunctionDefinitionCallableV1"
    assert isinstance(dormant.definition, AsyncFunctionDef)
    assert dormant.definition.fragment.source_cid == module.source_cid
    assert dormant.definition.fragment.span.start == 0
    assert dormant.definition.fragment.span.end == 62


def test_module_prefix_refuses_synchronous_async_function_application(
    tmp_path: Path,
) -> None:
    """Calling an async definition cannot reuse synchronous source-frame meaning."""
    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_python_source import manager_construction
    from sugar_source_tree.nodes import Call
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.tree import SourceFile

    source = "async def produce(value):\n" "    return value\n" "result = produce(7)\n"
    dist = _dist(
        tmp_path,
        name="async-module-call-pkg",
        files={"async_module_call_pkg/__init__.py": source},
    )
    module = DependencyArtifactGraph.authenticate(dist).modules["async_module_call_pkg"]

    exits = manager_construction._module_prefix_outcome(
        module, ast.parse(source).body[-1]
    )
    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    callable_floor = completed.value.context.temporal.value_if_bound("produce")
    tree = SourceFile.from_path(
        tmp_path / "async_module_call_pkg/__init__.py",
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    call = next(node for node in tree.nodes() if isinstance(node, Call))
    occurrence = manager_construction._call_coordinate(call)

    with pytest.raises(SugarNotWritten) as raised:
        CallableApplication(
            (TermValue(7),),
            (),
            call.fragment,
            owner="async module call test",
            call_occurrence=occurrence,
        ).apply(callable_floor, completed.value.context)

    assert raised.value.owner == "module function definition application"
    assert raised.value.blame.source_cid == module.source_cid
    assert raised.value.observed == (
        "AsyncFunctionDef reached the synchronous module callable floor"
    )
    assert raised.value.requested == "an authenticated coroutine-construction Floor"


def test_module_prefix_sync_function_application_remains_completed(
    tmp_path: Path,
) -> None:
    """Truthful twin: an ordinary FunctionDef keeps synchronous frame application."""
    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_python_source import manager_construction
    from sugar_source_tree.nodes import Call
    from sugar_source_tree.tree import SourceFile

    source = "def produce(value):\n" "    return value\n" "result = produce(7)\n"
    dist = _dist(
        tmp_path,
        name="sync-module-call-pkg",
        files={"sync_module_call_pkg/__init__.py": source},
    )
    module = DependencyArtifactGraph.authenticate(dist).modules["sync_module_call_pkg"]

    exits = manager_construction._module_prefix_outcome(
        module, ast.parse(source).body[-1]
    )

    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    callable_floor = completed.value.context.temporal.value_if_bound("produce")
    tree = SourceFile.from_path(
        tmp_path / "sync_module_call_pkg/__init__.py",
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    call = next(node for node in tree.nodes() if isinstance(node, Call))
    occurrence = manager_construction._call_coordinate(call)

    result = CallableApplication(
        (TermValue(7),),
        (),
        call.fragment,
        owner="sync module call test",
        call_occurrence=occurrence,
    ).apply(callable_floor, completed.value.context)

    assert isinstance(result, Complete)
    assert type(result.value) is TermValue
    assert result.value.value == 7


def test_module_prefix_refuses_decorated_async_definition_before_completion(
    tmp_path: Path,
) -> None:
    """A different async-definition occurrence cannot borrow plain publication."""
    from sugar_lift_python_source import manager_construction
    from sugar_source_tree.panic import SugarNotWritten

    source = (
        "@decorate\n"
        "async def dormant():\n"
        "    return 1\n"
        "def build():\n"
        "    return dormant\n"
    )
    dist = _dist(
        tmp_path,
        name="decorated-async-module-function-pkg",
        files={"decorated_async_module_function_pkg/__init__.py": source},
    )
    module = DependencyArtifactGraph.authenticate(dist).modules[
        "decorated_async_module_function_pkg"
    ]

    with pytest.raises(SugarNotWritten) as raised:
        manager_construction._module_prefix_outcome(module, ast.parse(source).body[-1])

    assert raised.value.owner == "module function definition execution"
    assert raised.value.blame.source_cid == module.source_cid
    assert raised.value.blame.span.start == 10
    assert raised.value.blame.span.end == 43
    assert (
        raised.value.observed
        == "decorated AsyncFunctionDef has no completed publication"
    )


def test_module_async_function_application_stays_typed_loud_while_plain_function_applies(
    tmp_path: Path,
) -> None:
    """Publication does not authorize synchronous execution of an async frame."""
    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_python_source import manager_construction
    from sugar_source_tree.panic import SugarNotWritten

    source = (
        "async def async_target():\n"
        "    return 1\n"
        "def plain_target():\n"
        "    return 1\n"
        "def build():\n"
        "    return async_target\n"
    )
    dist = _dist(
        tmp_path,
        name="async-call-application-pkg",
        files={"async_call_application_pkg/__init__.py": source},
    )
    module = DependencyArtifactGraph.authenticate(dist).modules[
        "async_call_application_pkg"
    ]
    published = manager_construction._module_prefix_outcome(
        module, ast.parse(source).body[-1]
    )
    async_callable = published.exits[0].value.context.temporal.value_if_bound(
        "async_target"
    )
    with pytest.raises(SugarNotWritten) as raised:
        CallableApplication((), (), async_callable.definition.fragment).apply(
            async_callable, None
        )
    assert raised.value.owner == "module function definition application"
    assert "AsyncFunctionDef" in raised.value.observed

    plain_module = DependencyArtifactGraph.authenticate(
        _dist(
            tmp_path / "plain",
            name="plain-call-application-pkg",
            files={
                "plain_call_application_pkg/__init__.py": source.replace(
                    "return async_target", "return plain_target"
                )
            },
        )
    ).modules["plain_call_application_pkg"]
    plain_published = manager_construction._module_prefix_outcome(
        plain_module, ast.parse(source).body[-1]
    )
    plain_callable = plain_published.exits[0].value.context.temporal.value_if_bound(
        "plain_target"
    )
    applied = CallableApplication((), (), plain_callable.definition.fragment).apply(
        plain_callable, None
    )
    assert isinstance(applied, Complete)


def test_module_prefix_constructs_one_subscript_delete_statement(
    tmp_path: Path,
) -> None:
    """A module prefix executes its exact subscript delete target."""
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_python_source import manager_construction

    source = "values = [1, 2, 3]\ndel values[-2:]\nresult = values\n"
    dist = _dist(
        tmp_path,
        name="module-delete-prefix-pkg",
        files={"module_delete_prefix_pkg/__init__.py": source},
    )
    module = DependencyArtifactGraph.authenticate(dist).modules[
        "module_delete_prefix_pkg"
    ]

    exits = manager_construction._module_prefix_outcome(
        module, ast.parse(source).body[-1]
    )

    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)


def test_module_prefix_chained_names_share_one_rhs_value(tmp_path: Path) -> None:
    """``left = right = RHS`` evaluates once and binds one resulting Floor."""
    from sugar_lift_py_tests.floor import NoneValue
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_python_source import manager_construction

    source = "left = right = None\nresult = left\n"
    dist = _dist(
        tmp_path,
        name="module-chained-assignment-pkg",
        files={"module_chained_assignment_pkg/__init__.py": source},
    )
    module = DependencyArtifactGraph.authenticate(dist).modules[
        "module_chained_assignment_pkg"
    ]

    exits = manager_construction._module_prefix_outcome(
        module, ast.parse(source).body[-1]
    )

    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    left = completed.value.context.temporal.value_if_bound("left")
    right = completed.value.context.temporal.value_if_bound("right")
    assert type(left) is NoneValue
    assert right is left


def test_stdlib_makecodes_return_is_rebound_before_exact_slice_delete() -> None:
    """The real ``re._constants`` prefix deletes from its returned ListValue."""
    from sugar_lift_py_tests.floor import CallSiteValue, ListValue
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_python_source import manager_construction

    graph = DependencyArtifactGraph.authenticate_stdlib_module("re")
    module = graph.modules["re._constants"]
    parsed = ast.parse(module.source)
    delete = next(
        statement
        for statement in parsed.body
        if isinstance(statement, ast.Delete) and statement.lineno == 124
    )
    next_statement = next(
        statement for statement in parsed.body if statement.lineno > delete.lineno
    )
    assignment = next(
        statement
        for statement in parsed.body
        if isinstance(statement, ast.Assign)
        and statement.lineno == 75
        and isinstance(statement.value, ast.Call)
    )
    expected_count = len(assignment.value.args) - 2

    exits = manager_construction._module_prefix_outcome(
        module, next_statement, graph=graph
    )

    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    opcodes = completed.value.context.temporal.value_if_bound("OPCODES")
    assert type(opcodes) is ListValue
    assert not isinstance(opcodes, CallSiteValue)
    assert len(opcodes.elements) == expected_count


def test_bodyless_call_result_cannot_be_promoted_to_delete_list(tmp_path: Path) -> None:
    """Lying twin: an unresolved return stays loud at the exact delete owner."""
    from sugar_lift_python_source import manager_construction
    from sugar_source_tree.panic import SugarNotWritten

    source = "OPCODES = external()\ndel OPCODES[-2:]\nafter = 1\n"
    dist = _dist(
        tmp_path,
        name="bodyless-delete-pkg",
        files={"bodyless_delete_pkg/__init__.py": source},
    )
    module = DependencyArtifactGraph.authenticate(dist).modules["bodyless_delete_pkg"]
    locus = ast.parse(source).body[-1]

    with pytest.raises(SugarNotWritten) as raised:
        manager_construction._module_prefix_outcome(module, locus)

    assert raised.value.owner == "SubscriptDeleteEffectSugar._delete"
    assert raised.value.observed == (
        "undischarged subscript delete over runtime-selected receiver"
    )


def test_module_prefix_execution_publishes_exact_decorator_result(
    tmp_path: Path,
) -> None:
    """A source decorator publishes its returned Floor, never the raw class."""
    from sugar_lift_py_tests.floor import ClassDefinitionValue
    from sugar_lift_py_tests.floor.decorated_class_value import DecoratedClassValue
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_python_source import manager_construction

    source = (
        "def identity(candidate):\n"
        "    return candidate\n"
        "@identity\n"
        "class Published:\n"
        "    TOKEN = 7\n"
        "def build():\n"
        "    return Published\n"
    )
    dist = _dist(
        tmp_path,
        name="module-decoration-prefix-pkg",
        files={"module_decoration_prefix_pkg/__init__.py": source},
    )
    module = DependencyArtifactGraph.authenticate(dist).modules[
        "module_decoration_prefix_pkg"
    ]

    exits = manager_construction._module_prefix_outcome(
        module, ast.parse(source).body[-1]
    )

    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    published = completed.value.context.temporal.value_if_bound("Published")
    assert type(published) is DecoratedClassValue
    publication = published.publication
    assert type(publication.raw_class) is ClassDefinitionValue
    assert publication.final_class is publication.raw_class
    assert len(publication.decorator_applications) == 1
    application = publication.decorator_applications[0]
    assert application.input_floor is publication.raw_class
    assert application.output_floor is publication.final_class
    assert publication.binding_occurrence == (
        publication.raw_class.binding_target_occurrence
    )


def test_module_prefix_execution_publishes_exact_metaclass_result(
    tmp_path: Path,
) -> None:
    """Metaclass application retains its four exact source-owned actuals."""
    from sugar_lift_py_tests.floor import DictValue, StringValue
    from sugar_lift_py_tests.floor.decorated_class_value import MetaclassClassValue
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_python_source import manager_construction

    source = (
        "class Meta:\n"
        "    def __new__(metacls, name, bases, namespace):\n"
        "        return namespace\n"
        "class Published(metaclass=Meta):\n"
        "    TOKEN = 7\n"
        "def build():\n"
        "    return Published\n"
    )
    dist = _dist(
        tmp_path,
        name="module-metaclass-prefix-pkg",
        files={"module_metaclass_prefix_pkg/__init__.py": source},
    )
    module = DependencyArtifactGraph.authenticate(dist).modules[
        "module_metaclass_prefix_pkg"
    ]

    exits = manager_construction._module_prefix_outcome(
        module, ast.parse(source).body[-1]
    )

    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    published = completed.value.context.temporal.value_if_bound("Published")
    assert type(published) is MetaclassClassValue
    publication = published.publication
    assert publication.metaclass_floor is (
        completed.value.context.temporal.value_if_bound("Meta")
    )
    assert type(publication.namespace_floor) is DictValue
    assert publication.final_class is publication.namespace_floor
    assert tuple(
        key.value
        for key, _value in publication.namespace_floor.entries
        if type(key) is StringValue
    ) == ("TOKEN",)
    assert publication.raw_class.binding_target_occurrence == (
        publication.binding_occurrence
    )


@pytest.mark.parametrize(
    ("class_keywords", "observed"),
    (
        ("flag=True", "unsupported class creation keyword flag"),
        ("**{'flag': True}", "unsupported class creation keyword **"),
    ),
)
def test_module_prefix_refuses_untransported_class_creation_keywords(
    tmp_path: Path, class_keywords: str, observed: str
) -> None:
    """Only the exact metaclass keyword has a constructed publication path."""
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_lift_python_source import manager_construction

    source = (
        f"class Published({class_keywords}):\n"
        "    TOKEN = 7\n"
        "def build():\n"
        "    return Published\n"
    )
    dist = _dist(
        tmp_path,
        name="module-class-keyword-prefix-pkg",
        files={"module_class_keyword_prefix_pkg/__init__.py": source},
    )
    module = DependencyArtifactGraph.authenticate(dist).modules[
        "module_class_keyword_prefix_pkg"
    ]

    with pytest.raises(SugarNotWritten) as raised:
        manager_construction._module_prefix_outcome(module, ast.parse(source).body[-1])

    assert raised.value.owner == "module definition execution"
    assert raised.value.observed == observed
    assert raised.value.requested == "one transported class creation keyword roster"


def test_module_prefix_without_class_creation_keywords_still_publishes(
    tmp_path: Path,
) -> None:
    """Truthful twin: an empty keyword roster needs no invented transport."""
    from sugar_lift_py_tests.floor import ClassDefinitionValue
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_python_source import manager_construction

    source = (
        "class Published:\n" "    TOKEN = 7\n" "def build():\n" "    return Published\n"
    )
    dist = _dist(
        tmp_path,
        name="module-class-no-keyword-prefix-pkg",
        files={"module_class_no_keyword_prefix_pkg/__init__.py": source},
    )
    module = DependencyArtifactGraph.authenticate(dist).modules[
        "module_class_no_keyword_prefix_pkg"
    ]

    exits = manager_construction._module_prefix_outcome(
        module, ast.parse(source).body[-1]
    )

    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    published = exits.exits[0].value.context.temporal.value_if_bound("Published")
    assert type(published) is ClassDefinitionValue


def test_prefix_adapter_propagates_missing_construction_producer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing producer is loud, never translated into dynamic export."""
    from sugar_lift_python_source import (
        dependency_export_adapter,
        manager_construction,
    )

    def missing_producer(_module, _locus):
        raise ImportError("construction producer unavailable")

    monkeypatch.setattr(
        manager_construction,
        "prefix_has_completed_fallthrough",
        missing_producer,
    )
    locus = ast.parse("value = 1\n").body[0]
    with pytest.raises(ImportError, match="construction producer unavailable"):
        dependency_export_adapter._prefix_has_completed_fallthrough(
            SimpleNamespace(), locus
        )


def test_prefix_adapter_routes_exact_graph_and_session_to_module_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Export admission consumes the authenticated module-prefix producer."""
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_python_source import (
        dependency_export_adapter,
        manager_construction,
    )
    from sugar_lift_python_source.resolution_session import SourceResolutionSession

    source = "value = 1\ndef build():\n    return value\n"
    dist = _dist(
        tmp_path,
        name="prefix-consumer-pkg",
        files={"prefix_consumer_pkg/__init__.py": source},
    )
    graph = DependencyArtifactGraph.authenticate(dist)
    module = graph.modules["prefix_consumer_pkg"]
    locus = ast.parse(source).body[-1]
    session = SourceResolutionSession()
    observed = []

    def completed_prefix(actual_module, actual_locus, *, graph, session):
        observed.append((actual_module, actual_locus, graph, session))
        return ExitSet.completed(SimpleNamespace(can_fall_through=True))

    monkeypatch.setattr(
        manager_construction, "_module_prefix_outcome", completed_prefix
    )

    assert dependency_export_adapter._prefix_has_completed_fallthrough(
        module, locus, graph=graph, session=session
    )
    assert observed == [(module, locus, graph, session)]


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


def test_prefix_multi_face_if_refuses_as_named_dynamic_export(tmp_path: Path) -> None:
    """Unresolved multi-face prefix stays a named gap — never AST-admitted."""
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
