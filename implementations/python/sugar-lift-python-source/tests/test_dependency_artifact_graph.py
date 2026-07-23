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
        package_source=("def __getattr__(name):\n" "    return object()\n"),
        implementation_source="def build(value):\n    return value\n",
    )
    graph = DependencyArtifactGraph.authenticate(distribution)

    demand = _demand(tmp_path)
    result = resolve_import_binding(demand, graph=graph)

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

    result = resolve_import_binding(demand, graph=graph)

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
