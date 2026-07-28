# SPDX-License-Identifier: MIT OR Apache-2.0
from __future__ import annotations

import csv
from dataclasses import replace
import importlib.metadata
import json
from pathlib import Path
import sys
from types import MappingProxyType

import pytest
from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1

from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactAuthenticationError,
    DependencyArtifactGraph,
    AuthenticatedModuleSourceV1,
    PythonObjectResolutionGapV1,
    ResolvedPythonObjectV1,
    resolve_import_binding,
    export_statement_coverage,
)
from sugar_lift_python_source.canonical import blake3_512_of, cid_of_json
from sugar_lift_python_source.external_exception_construction import (
    AuthenticatedProviderExceptionTypeV1,
    ExternalExceptionConstructionGap,
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


def _install_stub_defined_distribution(root: Path) -> importlib.metadata.Distribution:
    package = root / "provider_pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from provider_pkg.lib import ProviderError, OtherError\n",
        encoding="utf-8",
    )
    (package / "lib.pyi").write_text(
        "class ProviderError(Exception): ...\n" "class OtherError(Exception): ...\n",
        encoding="utf-8",
    )
    metadata = root / "provider_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: provider-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text("provider_pkg\n", encoding="utf-8")
    recorded = (
        "provider_pkg/__init__.py",
        "provider_pkg/lib.pyi",
        "provider_dist-1.0.dist-info/METADATA",
        "provider_dist-1.0.dist-info/top_level.txt",
        "provider_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for path in recorded:
            writer.writerow((path, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _install_cython_include_distribution(
    root: Path,
) -> importlib.metadata.Distribution:
    package = root / "cython_provider"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from cython_provider.lib import ProviderError\n",
        encoding="utf-8",
    )
    (package / "lib.pyx").write_text(
        'include "errors.pxi"\n',
        encoding="utf-8",
    )
    (package / "errors.pxi").write_text(
        "class ProviderBase(Exception):\n"
        "    pass\n\n"
        "class ProviderError(ValueError, ProviderBase):\n"
        "    pass\n",
        encoding="utf-8",
    )
    metadata = root / "cython_provider_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: cython-provider-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text("cython_provider\n", encoding="utf-8")
    recorded = (
        "cython_provider/__init__.py",
        "cython_provider/lib.pyx",
        "cython_provider/errors.pxi",
        "cython_provider_dist-1.0.dist-info/METADATA",
        "cython_provider_dist-1.0.dist-info/top_level.txt",
        "cython_provider_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for path in recorded:
            writer.writerow((path, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _install_returned_module_gate(root: Path) -> importlib.metadata.Distribution:
    package = root / "gate_pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "import sys\n"
        "def load(module_name):\n"
        "    loaded = sys.modules[module_name]\n"
        "    return loaded\n",
        encoding="utf-8",
    )
    metadata = root / "gate_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: gate-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text("gate_pkg\n", encoding="utf-8")
    recorded = (
        "gate_pkg/__init__.py",
        "gate_dist-1.0.dist-info/METADATA",
        "gate_dist-1.0.dist-info/top_level.txt",
        "gate_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for path in recorded:
            writer.writerow((path, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def test_stub_defined_provider_exception_resolves_to_its_definition(tmp_path: Path):
    """Truthful: an authenticated .pyi class is defining source, not opacity."""
    graph = DependencyArtifactGraph.authenticate(
        _install_stub_defined_distribution(tmp_path)
    )
    demand = _demand(
        tmp_path,
        "import provider_pkg\nprovider_pkg.ProviderError()\n",
    )

    result = resolve_import_binding(demand, graph=graph)

    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.module_name == "provider_pkg.lib"
    assert result.definition.kind == "class"
    assert result.definition.name == "ProviderError"
    assert graph.modules["provider_pkg.lib"].source_seat == "provider_pkg/lib.pyi"
    testimony = AuthenticatedProviderExceptionTypeV1.from_resolved(
        graph=graph,
        source_attribute="ProviderError",
        resolved=result,
    )
    assert testimony.resolved is result
    assert testimony.source_attribute == "ProviderError"
    assert testimony.ancestry


def test_cython_included_provider_exception_resolves_to_defining_source(
    tmp_path: Path,
):
    """Truthful: a recorded .pyx include reaches its recorded class preimage."""
    graph = DependencyArtifactGraph.authenticate(
        _install_cython_include_distribution(tmp_path)
    )
    demand = _demand(
        tmp_path,
        "import cython_provider\ncython_provider.ProviderError()\n",
    )

    result = resolve_import_binding(demand, graph=graph)

    assert isinstance(result, ResolvedPythonObjectV1), result
    assert result.module_name == "cython_provider.lib"
    assert result.definition.name == "ProviderError"
    assert result.definition.kind == "class"
    source_file = next(
        item for item in graph.files if item.content_cid == result.source_cid
    )
    assert source_file.source_seat == "cython_provider/errors.pxi"
    testimony = AuthenticatedProviderExceptionTypeV1.from_resolved(
        graph=graph,
        source_attribute="ProviderError",
        resolved=result,
    )
    assert testimony.resolved is result
    assert [term.args[1].value for term in testimony.ancestry] == [
        "cython_provider.lib.ProviderError",
        "ValueError",
        "Exception",
        "BaseException",
        "ProviderBase",
    ]


def test_stub_provider_cannot_testify_for_a_different_exception(tmp_path: Path):
    """Lying: ProviderError testimony cannot authenticate OtherError."""
    graph = DependencyArtifactGraph.authenticate(
        _install_stub_defined_distribution(tmp_path)
    )
    truthful = resolve_import_binding(
        _demand(tmp_path, "import provider_pkg\nprovider_pkg.ProviderError()\n"),
        graph=graph,
    )
    lying = resolve_import_binding(
        _demand(tmp_path, "import provider_pkg\nprovider_pkg.OtherError()\n"),
        graph=graph,
    )

    assert isinstance(truthful, ResolvedPythonObjectV1)
    assert isinstance(lying, ResolvedPythonObjectV1)
    assert truthful.definition.name == "ProviderError"
    assert lying.definition.name == "OtherError"
    assert truthful.cid != lying.cid
    with pytest.raises(
        ExternalExceptionConstructionGap,
        match="source binds ProviderError, provider resolved OtherError",
    ):
        AuthenticatedProviderExceptionTypeV1.from_resolved(
            graph=graph,
            source_attribute="ProviderError",
            resolved=lying,
        )


def test_returned_module_binding_constructs_provider_exception_without_vendor_name(
    tmp_path: Path,
):
    """A source-returned module carries its provider class definition through."""
    from sugar_lift_python_source.external_exception_construction import (
        construct_provider_exception_attribute,
    )
    from sugar_lift_python_source.resolution_session import SourceResolutionSession
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.tree import SourceFile

    provider = _install_stub_defined_distribution(tmp_path)
    gate = _install_returned_module_gate(tmp_path)
    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "import gate_pkg\n"
        'provider = gate_pkg.load("provider_pkg")\n'
        "def expected():\n"
        "    return provider.ProviderError\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(consumer)))
    attribute = next(
        node
        for node in tree.nodes()
        if node.kind == "Attribute" and node.attr == "ProviderError"
    )

    testimony = construct_provider_exception_attribute(
        attribute,
        root=tmp_path,
        path=consumer,
        graph_cache={},
        session=SourceResolutionSession(),
        distribution_index={"gate_pkg": gate, "provider_pkg": provider},
    )

    assert testimony is not None
    assert testimony.resolved.definition.name == "ProviderError"
    assert testimony.resolved.module_name == "provider_pkg.lib"
    assert testimony.class_value().name == "provider_pkg.lib.ProviderError"


def _demand(
    root: Path, source: str = "import example_pkg\nexample_pkg.build(1)\n"
) -> AuthenticatedImportUseV1:
    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts

    path = root / "consumer.py"
    path.write_text(source, encoding="utf-8")
    source_cid = blake3_512_of(source.encode("utf-8"))
    receipts, outcomes = authenticated_import_use_receipts(
        root, path, source, source_cid, module_identities={}
    )
    assert set(outcomes.values()) == {"authenticated-import-use"}
    assert len(receipts) == 1
    return receipts[0]


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
    result = resolve_import_binding(demand, graph=graph)

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
    result = resolve_import_binding(demand, graph=graph)
    assert isinstance(result, ResolvedPythonObjectV1)

    encoded = json.loads(json.dumps(result.to_value(), sort_keys=True))
    decoded = ResolvedPythonObjectV1.from_value(
        encoded, graph=graph, authenticated_use=demand
    )

    assert decoded == result
    assert decoded.cid == result.cid
    assert decoded.definition.kind == "class"


def test_dynamic_export_stays_a_typed_loud_gap(tmp_path: Path) -> None:
    distribution = _install_distribution(
        tmp_path,
        package_source=("def __getattr__(name):\n    return object()\n"),
        implementation_source="def build(value):\n    return value\n",
    )
    graph = DependencyArtifactGraph.authenticate(distribution)

    demand = _demand(tmp_path)
    result = resolve_import_binding(demand, graph=graph)

    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"
    assert result.import_binding_cid.startswith("blake3-512:")
    assert result.distribution_artifact_cid == graph.distribution_artifact_cid


def test_decorated_definition_resolves_without_decorator_name_authority(
    tmp_path: Path,
) -> None:
    """``@decorator def name`` is still a static export of ``name``.

    Mid-band residual diagnosis: re-export of ``@contextmanager`` resources
    stopped at dynamic-export solely because any decorator_list was treated
    as opaque. Export resolution must not require recognizing the decorator
    spelling; construction may still refuse opaque decorator application.
    """
    distribution = _install_distribution(
        tmp_path,
        package_source="from example_pkg.implementation import build\n",
        implementation_source=(
            "def wrap(fn):\n"
            "    return fn\n\n"
            "@wrap\n"
            "def build(value):\n"
            "    return value\n"
        ),
    )
    graph = DependencyArtifactGraph.authenticate(distribution)
    result = resolve_import_binding(_demand(tmp_path), graph=graph)

    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.definition.kind == "function"
    assert result.definition.name == "build"
    assert result.module_name == "example_pkg.implementation"
    assert result.reexport_warrants
    assert "example_pkg" not in sys.modules


def test_contextmanager_decorated_reexport_resolves_as_definition(
    tmp_path: Path,
) -> None:
    """Re-exported ``@contextmanager`` factory resolves to its definition.

    εR board note: this unblocks *export* for ensure_clean-class sites.
    Full contract ΔR still requires constructing the body/disposition; body
    opaques remain separate residual. Do not claim tens-of-sites With ΔR
    from export alone.
    """
    distribution = _install_distribution(
        tmp_path,
        package_source="from example_pkg.implementation import make_resource\n",
        implementation_source=(
            "from contextlib import contextmanager\n\n"
            "@contextmanager\n"
            "def make_resource():\n"
            "    yield 9\n"
        ),
    )
    graph = DependencyArtifactGraph.authenticate(distribution)
    demand = _demand(
        tmp_path,
        "import example_pkg\nwith example_pkg.make_resource():\n    pass\n",
    )
    result = resolve_import_binding(demand, graph=graph)

    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.definition.name == "make_resource"
    assert result.definition.kind == "function"
    assert result.module_name == "example_pkg.implementation"


def test_real_pandas_source_visible_reexport_resolves_without_name_authority() -> None:
    """Live residual membrane: hard-abort raises must not poison later re-exports.

    Installed pandas ``__init__`` runs dependency-check raises before source-visible
    ``ImportFrom`` re-exports.  Production has no pandas spelling or module
    admission — this is open-boundary residual against the live wheel only.
    """
    graph = DependencyArtifactGraph.authenticate(
        importlib.metadata.distribution("pandas")
    )
    import tempfile
    from pathlib import Path as P

    root = P(tempfile.mkdtemp())
    demand = _demand(root, "import pandas as pd\npd.array([1])\n")
    result = resolve_import_binding(demand, graph=graph)

    assert isinstance(result, ResolvedPythonObjectV1), getattr(result, "kind", result)
    assert result.definition.name == "array"
    assert result.definition.kind == "function"
    assert result.module_name != "pandas"
    assert result.reexport_warrants
    # No vendor arm: resolution is content/source chain, not a spelling table.


def test_real_pytest_reexport_resolves_without_manager_name_recognition(
    tmp_path: Path,
) -> None:
    graph = DependencyArtifactGraph.authenticate(
        importlib.metadata.distribution("pytest")
    )
    demand = _demand(tmp_path, "import pytest\npytest.raises(ValueError)\n")

    result = resolve_import_binding(demand, graph=graph)

    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.definition.name == "raises"
    assert result.definition.kind == "function"
    assert result.module_name != "pytest"
    assert result.reexport_warrants
    assert result.definition.source_cid == result.source_cid


def test_stdlib_module_resolves_renamed_export_through_dependency_graph(
    tmp_path: Path,
) -> None:
    graph = DependencyArtifactGraph.authenticate_stdlib_module("contextlib")
    demand = _demand(
        tmp_path,
        "from contextlib import suppress as RenamedBoundary\n"
        "RenamedBoundary(ValueError)\n",
    )

    result = resolve_import_binding(demand, graph=graph)

    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.definition.kind == "class"
    assert result.definition.name == "suppress"
    assert result.module_name == "contextlib"
    assert graph.modules["contextlib"].source_cid == result.source_cid


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
        match="module source is not projected",
    ):
        replace(graph, modules=MappingProxyType({"invented.module": invented}))


def test_fabricated_import_binding_mapping_is_rejected_at_resolution_door(
    tmp_path: Path,
) -> None:
    graph = DependencyArtifactGraph.authenticate(
        _install_distribution(
            tmp_path,
            package_source="from example_pkg.implementation import build\n",
            implementation_source="def build(value):\n    return value\n",
        )
    )
    fabricated = _demand(tmp_path).import_binding.to_value()

    with pytest.raises(
        DependencyArtifactAuthenticationError,
        match="AuthenticatedImportUseV1",
    ):
        resolve_import_binding(fabricated, graph=graph)


def test_final_checked_import_use_rejects_fabricated_definition_coordinate(
    tmp_path: Path,
) -> None:
    graph = DependencyArtifactGraph.authenticate(
        _install_distribution(
            tmp_path,
            package_source="from example_pkg.implementation import build\n",
            implementation_source="def build(value):\n    return value\n",
        )
    )
    receipt = _demand(tmp_path)
    binding_value = receipt.import_binding.to_value()
    binding_value["definitionSite"]["startLine"] = 999
    binding_cid = cid_of_json(binding_value)
    forged_binding = replace(
        receipt.import_binding, value=binding_value, cid=binding_cid
    )
    use = dict(receipt.use)
    use["importBindingCid"] = binding_cid
    use["cid"] = cid_of_json({key: value for key, value in use.items() if key != "cid"})
    demand = dict(receipt.demand)
    demand["importBinding"] = binding_value
    demand["importBindingCid"] = binding_cid
    demand["authenticatedImportUse"] = use
    forged_receipt = replace(
        receipt,
        import_binding=forged_binding,
        use=use,
        demand=demand,
    )

    with pytest.raises(
        DependencyArtifactAuthenticationError,
        match="lexical revalidation",
    ):
        resolve_import_binding(forged_receipt, graph=graph)


def test_recomputed_outer_cid_cannot_authenticate_invented_resolved_artifact(
    tmp_path: Path,
) -> None:
    graph = DependencyArtifactGraph.authenticate(
        _install_distribution(
            tmp_path,
            package_source="from example_pkg.implementation import build\n",
            implementation_source="def build(value):\n    return value\n",
        )
    )
    demand = _demand(tmp_path)
    resolved = resolve_import_binding(demand, graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    forged = resolved.to_value()
    forged["moduleName"] = "invented.module"
    forged["cid"] = cid_of_json(
        {key: value for key, value in forged.items() if key != "cid"}
    )

    with pytest.raises(
        DependencyArtifactAuthenticationError,
        match="byte-identical",
    ):
        ResolvedPythonObjectV1.from_value(forged, graph=graph, authenticated_use=demand)


def test_final_reaching_definition_wins_without_decorator_name_recognition(
    tmp_path: Path,
) -> None:
    graph = DependencyArtifactGraph.authenticate(
        _install_distribution(
            tmp_path,
            package_source="from example_pkg.implementation import build\n",
            implementation_source=(
                "def build(value):\n    return 'typing-only'\n\n"
                "def build(value):\n    return value\n"
            ),
        )
    )
    resolved = resolve_import_binding(_demand(tmp_path), graph=graph)

    assert isinstance(resolved, ResolvedPythonObjectV1)
    assert resolved.definition.start_line == 4


def test_later_non_name_assignment_makes_export_dynamic(tmp_path: Path) -> None:
    graph = DependencyArtifactGraph.authenticate(
        _install_distribution(
            tmp_path,
            package_source="from example_pkg.implementation import build\n",
            implementation_source="def build(value):\n    return value\nbuild = 42\n",
        )
    )
    result = resolve_import_binding(_demand(tmp_path), graph=graph)

    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"


@pytest.mark.parametrize(
    ("implementation", "expected_line"),
    (
        (
            "def build(value):\n    return 'old'\n"
            "with object():\n"
            "    def build(value):\n        return value\n",
            4,
        ),
        (
            "def build(value):\n    return 'old'\n"
            "match 1:\n"
            "    case _:\n"
            "        def build(value):\n            return value\n",
            5,
        ),
        (
            "def build(value):\n    return 'old'\n"
            "try:\n"
            "    def build(value):\n        return value\n"
            "except* Exception:\n    pass\n",
            4,
        ),
    ),
    ids=("with", "match", "try-star"),
)
def test_compound_statement_later_definition_is_the_authenticated_export(
    tmp_path: Path, implementation: str, expected_line: int
) -> None:
    graph = DependencyArtifactGraph.authenticate(
        _install_distribution(
            tmp_path,
            package_source="from example_pkg.implementation import build\n",
            implementation_source=implementation,
        )
    )
    result = resolve_import_binding(_demand(tmp_path), graph=graph)

    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.definition.start_line == expected_line
    assert result.definition.start_line != 1


def test_with_suppressible_exceptional_prefix_does_not_authenticate_unreachable_export(
    tmp_path: Path,
) -> None:
    graph = DependencyArtifactGraph.authenticate(
        _install_distribution(
            tmp_path,
            package_source="from example_pkg.implementation import build\n",
            implementation_source=(
                "def build(value):\n    return 'old'\n"
                "with suppresses_exceptions():\n"
                "    raise RuntimeError()\n"
                "    def build(value):\n        return 'new'\n"
            ),
        )
    )

    result = resolve_import_binding(_demand(tmp_path), graph=graph)

    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"


def test_raise_inside_earlier_function_does_not_make_later_export_dynamic(
    tmp_path: Path,
) -> None:
    """A deferred raise is not a module-initialization edge.

    pandas._testing defines helpers containing ``raise`` before defining
    ``external_error_raised``. Walking into those earlier function bodies made
    the later, unconditional helper definition look dynamically reachable.
    """
    graph = DependencyArtifactGraph.authenticate(
        _install_distribution(
            tmp_path,
            package_source="from example_pkg.implementation import build\n",
            implementation_source=(
                "def earlier():\n"
                "    raise RuntimeError()\n\n"
                "def build(value):\n"
                "    return value\n"
            ),
        )
    )

    result = resolve_import_binding(_demand(tmp_path), graph=graph)

    assert isinstance(result, ResolvedPythonObjectV1)
    assert result.definition.start_line == 4


def test_export_transfer_exhaustively_classifies_running_ast_statement_grammar() -> (
    None
):
    missing, extra = export_statement_coverage()
    assert missing == []
    assert extra == []


def test_resolve_import_binding_amortizes_lexical_revalidation(tmp_path: Path) -> None:
    """Red instrument: resolution must not re-run #6090 once per receipt.

    pandas construction recensus paid ~0.95s × R full-module
    ``authenticated_import_uses`` revalidations inside ``resolve_import_binding``
    (R≈125–170 on hot files). Revalidation may stay exact; recompute frequency
    must be amortized to O(1) per consumer module, not Ω(R).

    See docs/audits/pandas-recensus-latency-bisect.md.
    """
    from sugar_lift_py_tests import import_binding as ib
    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts

    distribution = _install_distribution(
        tmp_path,
        package_source="from example_pkg.implementation import build\n",
        implementation_source="def build(value):\n    return value\n",
    )
    graph = DependencyArtifactGraph.authenticate(distribution)

    # N distinct call sites → N authenticated import-use receipts for one module.
    n_sites = 8
    lines = ["import example_pkg"] + [f"example_pkg.build({i})" for i in range(n_sites)]
    source = "\n".join(lines) + "\n"
    path = tmp_path / "consumer_many.py"
    path.write_text(source, encoding="utf-8")
    source_cid = blake3_512_of(source.encode("utf-8"))
    receipts, outcomes = authenticated_import_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    assert len(receipts) == n_sites
    assert set(outcomes.values()) == {"authenticated-import-use"}

    lexical_passes = {"count": 0}
    original = ib.authenticated_import_uses

    def counting_authenticated_import_uses(*args, **kwargs):
        lexical_passes["count"] += 1
        return original(*args, **kwargs)

    ib.authenticated_import_uses = counting_authenticated_import_uses
    try:
        for receipt in receipts:
            resolve_import_binding(receipt, graph=graph)
    finally:
        ib.authenticated_import_uses = original

    # One shared revalidation snapshot for the consumer module is enough.
    # Ω(n_sites) means each resolve re-ran the full lexical pass (the live bug).
    assert lexical_passes["count"] <= 1, (
        f"resolve_import_binding re-ran authenticated_import_uses "
        f"{lexical_passes['count']} times for {n_sites} receipts from one module; "
        f"amortize revalidation (cache or batch) so this stays O(1) per module"
    )


def test_resolve_export_amortizes_repeated_static_scans(tmp_path: Path) -> None:
    """Red instrument: same export must not re-walk module AST per receipt.

    After revalidation amortization, megamodule call-frame preconstruction still
    paid a full static export scan per import-use receipt (many repeats of the
    same symbol). Structural export resolution is pure in
    (distribution, module, name); recompute frequency must be O(unique exports).
    """
    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
    from sugar_lift_python_source import dependency_export_adapter as de
    from sugar_lift_python_source.resolution_session import SourceResolutionSession

    distribution = _install_distribution(
        tmp_path,
        package_source="from example_pkg.implementation import build\n",
        implementation_source="def build(value):\n    return value\n",
    )
    graph = DependencyArtifactGraph.authenticate(distribution)
    # One session, as a real population has: amortization is a property of the
    # session, not of the process.
    session = SourceResolutionSession()

    n_sites = 8
    lines = ["import example_pkg"] + [f"example_pkg.build({i})" for i in range(n_sites)]
    source = "\n".join(lines) + "\n"
    path = tmp_path / "consumer_export_many.py"
    path.write_text(source, encoding="utf-8")
    source_cid = blake3_512_of(source.encode("utf-8"))
    receipts, outcomes = authenticated_import_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    assert len(receipts) == n_sites

    scans = {"count": 0}
    original_block = de._export_block

    def counting_export_block(statements, name, initial):
        scans["count"] += 1
        return original_block(statements, name, initial)

    de._export_block = counting_export_block
    try:
        results = [
            resolve_import_binding(receipt, graph=graph, session=session)
            for receipt in receipts
        ]
    finally:
        de._export_block = original_block

    assert all(isinstance(item, ResolvedPythonObjectV1) for item in results)
    # First receipt: package reexport walk + implementation definition (2).
    # Further receipts must hit the top-level export cache (no more scans).
    assert scans["count"] <= 2, (
        f"resolve_export re-ran _export_block {scans['count']} times for "
        f"{n_sites} receipts of the same symbol; amortize export resolution"
    )
    # Same import binding → same resolved object identity; definition is shared.
    assert len({item.definition.fragment_cid for item in results}) == 1
    assert len({item.module_name for item in results}) == 1


def test_resolve_source_visible_frame_amortizes_repeated_materialize(
    tmp_path: Path,
) -> None:
    """Red instrument: same definition must not re-SourceFile per receipt.

    ``resolve_source_visible_frame`` materializes the target module and may
    sugar class bases. Repeating that per call-site receipt dominated
    megamodule preconstruction after export amortization.
    """
    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
    from sugar_lift_python_source import manager_construction as mc
    from sugar_lift_python_source.manager_construction import (
        resolve_source_visible_frame,
    )
    from sugar_lift_python_source.resolution_session import SourceResolutionSession
    from sugar_source_tree.tree import SourceFile

    distribution = _install_distribution(
        tmp_path,
        package_source="from example_pkg.implementation import build\n",
        implementation_source="def build(value):\n    return value\n",
    )
    graph = DependencyArtifactGraph.authenticate(distribution)
    session = SourceResolutionSession()

    n_sites = 6
    lines = ["import example_pkg"] + [f"example_pkg.build({i})" for i in range(n_sites)]
    source = "\n".join(lines) + "\n"
    path = tmp_path / "consumer_frame_many.py"
    path.write_text(source, encoding="utf-8")
    source_cid = blake3_512_of(source.encode("utf-8"))
    receipts, _ = authenticated_import_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    resolved = [resolve_import_binding(r, graph=graph) for r in receipts]
    assert all(isinstance(item, ResolvedPythonObjectV1) for item in resolved)

    materializations = {"count": 0}
    original_sf = SourceFile

    class CountingSourceFile(original_sf):
        def __init__(self, *args, **kwargs):
            materializations["count"] += 1
            super().__init__(*args, **kwargs)

    mc.SourceFile = CountingSourceFile  # type: ignore[misc, assignment]
    try:
        frames = [
            resolve_source_visible_frame(item, graph=graph, session=session)
            for item in resolved
        ]
    finally:
        mc.SourceFile = original_sf  # type: ignore[misc, assignment]

    assert all(isinstance(item, tuple) for item in frames)
    assert materializations["count"] <= 1, (
        f"resolve_source_visible_frame re-materialized SourceFile "
        f"{materializations['count']} times for {n_sites} receipts of one "
        f"definition; amortize source-visible frame projection"
    )
