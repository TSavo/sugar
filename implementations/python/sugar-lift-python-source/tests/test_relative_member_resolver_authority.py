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
from sugar_lift_python_source.canonical import blake3_512_of, cid_of_json
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactAuthenticationError,
    DependencyArtifactGraph,
    PythonObjectResolutionGapV1,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)


_CONSUMER = (
    "from sample_pkg import helper\n"
    "from sample_pkg.helper import FLAG as DIRECT\n"
    "helper.FLAG()\n"
    "DIRECT()\n"
    "helper.Box.FLAG()\n"
    "member = helper.FLAG\n"
)


def _distribution(
    root: Path, *, marker: str = "truth", include_helper: bool = True
) -> importlib.metadata.Distribution:
    package = root / "sample_pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "from . import helper\n", encoding="utf-8"
    )
    if include_helper:
        (package / "helper.py").write_text(
            f"def FLAG():\n    return {marker!r}\n\n"
            "class Box:\n"
            "    @staticmethod\n"
            "    def FLAG():\n"
            "        return 'nested'\n",
            encoding="utf-8",
        )
    metadata = root / "sample_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: sample-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text("sample_pkg\n", encoding="utf-8")
    recorded = [
        "sample_pkg/__init__.py",
        "sample_dist-1.0.dist-info/METADATA",
        "sample_dist-1.0.dist-info/top_level.txt",
        "sample_dist-1.0.dist-info/RECORD",
    ]
    if include_helper:
        recorded.insert(1, "sample_pkg/helper.py")
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _receipts(root: Path, *, suffix: str = ""):
    source = _CONSUMER + suffix
    path = root / "consumer.py"
    path.write_text(source, encoding="utf-8")
    source_cid = blake3_512_of(source.encode("utf-8"))
    calls, _ = authenticated_import_use_receipts(
        root, path, source, source_cid, module_identities={}
    )
    values, _ = authenticated_import_value_use_receipts(
        root, path, source, source_cid, module_identities={}
    )
    return calls, values


def _at_line(receipts, line: int) -> AuthenticatedImportUseV1:
    rows = tuple(row for row in receipts if row.use["useSite"]["startLine"] == line)
    assert len(rows) == 1, rows
    return rows[0]


def _member_value_at_line(receipts, line: int) -> AuthenticatedImportUseV1:
    rows = tuple(
        row
        for row in receipts
        if row.use["useSite"]["startLine"] == line
        and row.target_symbol == "python:sample_pkg.helper.FLAG"
        and row.use.get("exportedMemberPath") == ["FLAG"]
    )
    assert len(rows) == 1, rows
    return rows[0]


def test_direct_bound_export_and_one_member_extension_are_distinct_lawful_paths(
    tmp_path: Path,
) -> None:
    graph = DependencyArtifactGraph.authenticate(_distribution(tmp_path))
    calls, _ = _receipts(tmp_path)

    relative_member = resolve_import_binding(_at_line(calls, 3), graph=graph)
    direct_bound = resolve_import_binding(_at_line(calls, 4), graph=graph)

    assert type(relative_member) is ResolvedPythonObjectV1
    assert relative_member.module_name == "sample_pkg.helper"
    assert relative_member.definition.name == "FLAG"
    assert type(direct_bound) is ResolvedPythonObjectV1
    assert direct_bound.module_name == "sample_pkg.helper"
    assert direct_bound.definition == relative_member.definition


def test_relative_member_requires_exactly_one_suffix_and_an_authenticated_module(
    tmp_path: Path,
) -> None:
    graph = DependencyArtifactGraph.authenticate(_distribution(tmp_path))
    calls, _ = _receipts(tmp_path)

    two_suffixes = resolve_import_binding(_at_line(calls, 5), graph=graph)

    assert type(two_suffixes) is PythonObjectResolutionGapV1
    assert two_suffixes.kind == "target-outside-binding"

    missing_root = tmp_path / "missing"
    missing_root.mkdir()
    graph_without_helper = DependencyArtifactGraph.authenticate(
        _distribution(missing_root, include_helper=False)
    )
    missing_module = resolve_import_binding(_at_line(calls, 3), graph=graph_without_helper)
    assert type(missing_module) is PythonObjectResolutionGapV1
    assert missing_module.kind == "target-outside-binding"
    assert "sample_pkg.helper" not in graph_without_helper.modules


def test_value_member_path_must_match_the_authenticated_structural_suffix(
    tmp_path: Path,
) -> None:
    graph = DependencyArtifactGraph.authenticate(_distribution(tmp_path))
    _, values = _receipts(tmp_path)
    receipt = _member_value_at_line(values, 6)

    resolved = resolve_import_binding(receipt, graph=graph)
    assert type(resolved) is ResolvedPythonObjectV1
    assert receipt.use["exportedMemberPath"] == ["FLAG"]

    wrong_use = dict(receipt.use)
    wrong_use["exportedMemberPath"] = ["OTHER"]
    wrong_use["cid"] = cid_of_json(
        {key: value for key, value in wrong_use.items() if key != "cid"}
    )
    with pytest.raises(
        (ValueError, DependencyArtifactAuthenticationError)
    ):
        wrong_demand = dict(receipt.demand)
        wrong_demand["authenticatedImportUse"] = wrong_use
        reminted = replace(receipt, use=wrong_use, demand=wrong_demand)
        resolve_import_binding(reminted, graph=graph)


def test_call_and_value_receipts_cannot_substitute_for_each_other(
    tmp_path: Path,
) -> None:
    graph = DependencyArtifactGraph.authenticate(_distribution(tmp_path))
    calls, values = _receipts(tmp_path)
    call = _at_line(calls, 3)
    value = _member_value_at_line(values, 6)

    accepted_substitutions = []
    for label, truthful, foreign in (
        ("call-as-value", call, value),
        ("value-as-call", value, call),
    ):
        try:
            substituted = replace(
                truthful,
                use=foreign.use,
                demand=foreign.demand,
            )
            resolve_import_binding(substituted, graph=graph)
        except (ValueError, DependencyArtifactAuthenticationError):
            continue
        accepted_substitutions.append(label)
    assert accepted_substitutions == [], (
        "AuthenticatedImportUseV1 authority crossed closed call/value demand surfaces: "
        f"{accepted_substitutions}"
    )


def test_foreign_source_binding_use_and_graph_cannot_replay_member_resolution(
    tmp_path: Path,
) -> None:
    truthful_root = tmp_path / "truthful"
    foreign_root = tmp_path / "foreign"
    truthful_root.mkdir()
    foreign_root.mkdir()
    graph = DependencyArtifactGraph.authenticate(_distribution(truthful_root))
    foreign_graph = DependencyArtifactGraph.authenticate(
        _distribution(foreign_root, marker="foreign")
    )
    calls, _ = _receipts(truthful_root)
    foreign_calls, _ = _receipts(foreign_root, suffix="# foreign occurrence\n")
    truthful = _at_line(calls, 3)
    foreign = _at_line(foreign_calls, 3)

    resolved = resolve_import_binding(truthful, graph=graph)
    foreign_resolved = resolve_import_binding(foreign, graph=foreign_graph)
    assert type(resolved) is ResolvedPythonObjectV1
    assert type(foreign_resolved) is ResolvedPythonObjectV1
    assert resolved.source_cid != foreign_resolved.source_cid
    assert truthful.source_cid != foreign.source_cid
    assert truthful.import_binding.cid != foreign.import_binding.cid
    assert truthful.use["cid"] != foreign.use["cid"]

    with pytest.raises(
        DependencyArtifactAuthenticationError,
        match="not byte-identical to artifact re-resolution",
    ):
        ResolvedPythonObjectV1.from_value(
            resolved.to_value(), graph=foreign_graph, authenticated_use=foreign
        )

    with pytest.raises((ValueError, DependencyArtifactAuthenticationError)):
        reminted = replace(
            truthful,
            import_binding=foreign.import_binding,
            use=foreign.use,
            demand=foreign.demand,
        )
        resolve_import_binding(reminted, graph=graph)
