"""Discrimination teeth for authenticated package-relative member resolution."""

from __future__ import annotations

import csv
from dataclasses import replace
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.import_binding import (
    AuthenticatedImportUseV1,
    authenticated_import_use_receipts,
    authenticated_import_value_use_receipts,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    PythonObjectResolutionGapV1,
    resolve_import_binding,
)


def _graph(
    root: Path,
    package: str,
    *,
    include_helper: bool = True,
    source_suffix: str = "",
):
    source = (
        "from . import helper\n"
        "from .helper import build\n"
        "direct = helper\n"
        "value = helper.FLAG\n"
        "nested = helper.box.FLAG\n"
        "built = build()\n"
        "called = helper.build()\n"
        "nested_call = helper.box.build()\n"
        f"{source_suffix}"
    )
    files = {f"{package}/__init__.py": source}
    if include_helper:
        files[f"{package}/helper.py"] = "FLAG = 1\ndef build():\n    return FLAG\n"
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    metadata = root / f"{package}_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {package}\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text(f"{package}\n", encoding="utf-8")
    recorded = (
        *files,
        f"{metadata.name}/METADATA",
        f"{metadata.name}/top_level.txt",
        f"{metadata.name}/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    graph = DependencyArtifactGraph.authenticate(
        importlib.metadata.Distribution.at(metadata)
    )
    path = root / package / "__init__.py"
    source_cid = blake3_512_of(source.encode("utf-8"))
    value_receipts, _ = authenticated_import_value_use_receipts(
        root, path, source, source_cid, module_identities={}
    )
    call_receipts, _ = authenticated_import_use_receipts(
        root, path, source, source_cid, module_identities={}
    )
    return graph, value_receipts, call_receipts


def _receipt(receipts, path: list[str]):
    return next(row for row in receipts if row.use["exportedMemberPath"] == path)


def test_exact_relative_submodule_member_enters_authenticated_nested_module(
    tmp_path: Path,
) -> None:
    graph, receipts, _calls = _graph(tmp_path, "truth_package")

    result = resolve_import_binding(_receipt(receipts, ["FLAG"]), graph=graph)

    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "dynamic-export"
    assert result.module_name == "truth_package.helper"
    assert result.exported_name == "FLAG"


def test_relative_submodule_extension_refuses_wrong_path_cardinality(
    tmp_path: Path,
) -> None:
    graph, receipts, _calls = _graph(tmp_path, "cardinality_package")

    empty = resolve_import_binding(_receipt(receipts, []), graph=graph)
    nested = resolve_import_binding(_receipt(receipts, ["box", "FLAG"]), graph=graph)

    assert isinstance(empty, PythonObjectResolutionGapV1)
    assert empty.kind == "reexport-cycle"
    assert isinstance(nested, PythonObjectResolutionGapV1)
    assert nested.kind == "target-outside-binding"


def test_relative_submodule_extension_refuses_absent_or_foreign_graph(
    tmp_path: Path,
) -> None:
    truthful_graph, receipts, _calls = _graph(tmp_path / "truth", "truth_package")
    absent_graph, _, _ = _graph(
        tmp_path / "absent", "truth_package", include_helper=False
    )
    foreign_graph, _, _ = _graph(tmp_path / "foreign", "foreign_package")
    receipt = _receipt(receipts, ["FLAG"])

    absent = resolve_import_binding(receipt, graph=absent_graph)
    foreign = resolve_import_binding(receipt, graph=foreign_graph)

    assert (
        truthful_graph.distribution_artifact_cid
        != absent_graph.distribution_artifact_cid
    )
    assert isinstance(absent, PythonObjectResolutionGapV1)
    assert absent.kind == "target-outside-binding"
    assert isinstance(foreign, PythonObjectResolutionGapV1)
    assert foreign.kind == "target-outside-binding"


def test_relative_submodule_receipt_refuses_foreign_source_binding_use_and_remint(
    tmp_path: Path,
) -> None:
    _first_graph, first_rows, _ = _graph(tmp_path / "first", "shared_package")
    _second_graph, second_rows, _ = _graph(
        tmp_path / "second", "shared_package", source_suffix="# foreign bytes\n"
    )
    first = _receipt(first_rows, ["FLAG"])
    second = _receipt(second_rows, ["FLAG"])

    with pytest.raises(ValueError, match="source CID is stale"):
        replace(first, source=second.source)
    with pytest.raises(ValueError, match="cites another binding"):
        replace(first, import_binding=second.import_binding)
    with pytest.raises(ValueError, match="cites another binding"):
        replace(first, use=second.use)
    with pytest.raises(ValueError, match="was not minted by the lexical pass"):
        AuthenticatedImportUseV1(
            import_binding=first.import_binding,
            target_symbol=first.target_symbol,
            use=first.use,
            demand=first.demand,
            root=first.root,
            path=first.path,
            source=first.source,
            source_cid=first.source_cid,
            module_identities=first.module_identities,
            _authority=object(),
        )


def test_direct_bound_export_and_one_suffix_call_resolve_without_widening(
    tmp_path: Path,
) -> None:
    graph, _values, calls = _graph(tmp_path, "call_package")
    direct = next(
        row for row in calls if row.target_symbol == "python:call_package.helper.build"
    )
    member = next(
        row
        for row in calls
        if row.target_symbol == "python:call_package.helper.build"
        and row.import_binding.to_value()["localSlot"] == "helper"
    )

    direct_result = resolve_import_binding(direct, graph=graph)
    member_result = resolve_import_binding(member, graph=graph)

    assert direct_result.module_name == "call_package.helper"
    assert direct_result.definition.name == "build"
    assert member_result.module_name == "call_package.helper"
    assert member_result.definition.name == "build"


def test_two_suffix_call_and_value_suffix_mismatch_refuse(tmp_path: Path) -> None:
    graph, values, calls = _graph(tmp_path, "suffix_package")
    nested_call = next(
        row
        for row in calls
        if row.target_symbol == "python:suffix_package.helper.box.build"
    )
    value = _receipt(values, ["FLAG"])

    result = resolve_import_binding(nested_call, graph=graph)

    assert isinstance(result, PythonObjectResolutionGapV1)
    assert result.kind == "target-outside-binding"
    with pytest.raises(ValueError, match="stale targetSymbol"):
        replace(value, target_symbol="python:suffix_package.helper.OTHER")


def test_call_and_value_demands_cannot_substitute(tmp_path: Path) -> None:
    _graph_value, values, calls = _graph(tmp_path, "demand_package")
    value = _receipt(values, ["FLAG"])
    call = next(
        row
        for row in calls
        if row.target_symbol == "python:demand_package.helper.build"
        and row.import_binding.to_value()["localSlot"] == "helper"
    )

    with pytest.raises(ValueError, match="authenticatedImportUse"):
        replace(call, demand=value.demand)
    with pytest.raises(ValueError, match="authenticatedImportUse"):
        replace(value, demand=call.demand)
