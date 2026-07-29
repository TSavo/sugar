"""Test-first dependency authority for CPython stdlib ``re.search``."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import pytest

from sugar_lift_py_tests.import_binding import (
    authenticated_import_use_receipts,
    authenticated_import_value_use_receipts,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    AuthenticatedModuleSourceV1,
    DependencyArtifactAuthenticationError,
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import (
    _seat_import_value_use_receipts,
    resolve_source_visible_frame,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import Attribute, Call, FunctionDef
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.tree import SourceFile
SOURCE = (
    "import re\n"
    "def selected(subject):\n"
    "    return re.search(\"needle\", subject, re.I)\n"
)


def _receipts(tmp_path: Path):
    path = tmp_path / "consumer.py"
    path.write_text(SOURCE, encoding="utf-8")
    source_cid = blake3_512_of(SOURCE.encode("utf-8"))
    calls, _outcomes = authenticated_import_use_receipts(
        tmp_path, path, SOURCE, source_cid, module_identities={}
    )
    values, _ = authenticated_import_value_use_receipts(
        tmp_path, path, SOURCE, source_cid, module_identities={}
    )
    call = next(row for row in calls if row.target_symbol == "python:re.search")
    flag = next(row for row in values if row.target_symbol == "python:re.I")
    return call, flag


def test_exact_re_search_receipt_resolves_and_seats_cpython_definition_body(
    tmp_path: Path,
) -> None:
    call, _flag = _receipts(tmp_path)
    graph = DependencyArtifactGraph.authenticate_stdlib_module("re")

    resolved = resolve_import_binding(call, graph=graph)

    assert isinstance(resolved, ResolvedPythonObjectV1), resolved
    assert graph.artifact_kind == "stdlib"
    assert graph.distribution_name == "cpython-stdlib"
    assert graph.distribution_version == "cpython-312"
    assert resolved.distribution_artifact_cid == graph.distribution_artifact_cid
    assert resolved.import_binding_cid == call.import_binding.cid
    assert resolved.module_name == "re"
    assert resolved.definition.kind == "function"
    assert resolved.definition.name == "search"
    module = graph.modules["re"]
    assert module.source_seat == "re/__init__.py"
    assert module.source_cid.startswith("blake3-512:691bec")
    assert resolved.source_cid == module.source_cid
    use_site = call.use["useSite"]
    assert use_site["sourceCid"] == call.source_cid
    assert call.demand["authenticatedImportUse"] == call.use

    projected = resolve_source_visible_frame(resolved, graph=graph)

    assert isinstance(projected, tuple), projected
    frame, target = projected
    assert isinstance(target, FunctionDef)
    assert target.name == "search"
    assert frame.owner is target
    assert frame.body is target.body
    assert frame.definition_site.source_cid == module.source_cid
    assert frame.definition_site.source_cid == resolved.definition.source_cid


def test_alias_import_search_resolves_the_same_exact_stdlib_definition(
    tmp_path: Path,
) -> None:
    source = (
        "import re as regex\n"
        "def selected(subject):\n"
        "    return regex.search(\"needle\", subject, regex.I)\n"
    )
    path = tmp_path / "alias_consumer.py"
    path.write_text(source, encoding="utf-8")
    source_cid = blake3_512_of(source.encode("utf-8"))
    calls, _ = authenticated_import_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    call = next(row for row in calls if row.target_symbol == "python:re.search")
    graph = DependencyArtifactGraph.authenticate_stdlib_module("re")

    resolved = resolve_import_binding(call, graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    assert resolved.definition.name == "search"
    projected = resolve_source_visible_frame(resolved, graph=graph)
    assert isinstance(projected, tuple)
    frame, target = projected
    assert isinstance(target, FunctionDef)
    assert target.name == "search"
    assert frame.owner is target


@pytest.mark.parametrize(
    "source",
    [
        "def selected(re, subject):\n    return re.search(\"x\", subject)\n",
        "re = object()\ndef selected(subject):\n    return re.search(\"x\", subject)\n",
    ],
)
def test_shadowed_or_local_re_binding_mints_no_import_call_receipt(
    tmp_path: Path, source: str
) -> None:
    path = tmp_path / "shadowed.py"
    path.write_text(source, encoding="utf-8")

    receipts, outcomes = authenticated_import_use_receipts(
        tmp_path,
        path,
        source,
        blake3_512_of(source.encode("utf-8")),
        module_identities={},
    )

    assert not any(row.target_symbol == "python:re.search" for row in receipts)
    assert "python:re.search" not in repr(outcomes)


def test_same_name_tampered_use_definition_runtime_and_artifact_refuse(
    tmp_path: Path,
) -> None:
    call, _flag = _receipts(tmp_path)
    graph = DependencyArtifactGraph.authenticate_stdlib_module("re")
    resolved = resolve_import_binding(call, graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)

    with pytest.raises(ValueError):
        replace(call, source=SOURCE + "# foreign\n")
    with pytest.raises(ValueError):
        replace(call, use={**call.use, "cid": "blake3-512:" + "0" * 128})
    with pytest.raises(ValueError):
        replace(
            resolved,
            definition=replace(
                resolved.definition,
                name="search",
                source_cid="blake3-512:" + "1" * 128,
            ),
        )
    with pytest.raises(DependencyArtifactAuthenticationError):
        replace(graph, distribution_version="cpython-313")
    with pytest.raises(DependencyArtifactAuthenticationError):
        replace(graph.files[0], content=graph.files[0].content + b"\n# tampered\n")


def test_re_i_value_receipt_cannot_substitute_re_search_call_span(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    call, flag = _receipts(tmp_path)
    graph = DependencyArtifactGraph.authenticate_stdlib_module("re")

    assert flag.demand["kind"] == "import-value-use-demand"
    assert flag.target_symbol == "python:re.I"
    assert call.demand["kind"] == "call-contract-demand"
    assert call.target_symbol == "python:re.search"
    assert call.use["useSite"] != flag.use["useSite"]

    context = TreeConstructionContextV1.for_source_call_construction(
        workspace_root=str(tmp_path)
    )
    source_file = SourceFile(
        (SOURCE, "consumer.py", blake3_512_of(SOURCE.encode())),
        construction_context=context,
    )
    function = next(
        node for node in source_file.nodes() if isinstance(node, FunctionDef)
    )
    module = AuthenticatedModuleSourceV1(
        "consumer", "consumer.py", source_file.unit.source_cid, SOURCE
    )
    _seat_import_value_use_receipts(
        source_file=source_file,
        module=module,
        target=function,
        session=SourceResolutionSession(),
        context=context,
        dependency_graphs={"re": graph},
    )
    search_call = next(
        node
        for node in source_file.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Attribute)
        and node.func.attr == "search"
    )
    flag_node = next(
        node
        for node in source_file.nodes()
        if isinstance(node, Attribute) and node.attr == "I"
    )
    call_span = search_call.line_col_span()
    flag_span = flag_node.line_col_span()
    call_key = (
        call_span.start_line,
        call_span.start_col,
        call_span.end_line,
        call_span.end_col,
    )
    flag_key = (
        flag_span.start_line,
        flag_span.start_col,
        flag_span.end_line,
        flag_span.end_col,
    )

    assert source_file.unit.import_value_use_resolution(call_key) is None
    assert source_file.unit.import_value_use_resolution(flag_key) == flag
    with pytest.raises(BackendDefect, match="receipt testimony"):
        source_file.unit.seat_import_value_use_resolution(
            call_key, flag, source_cid=source_file.unit.source_cid
        )


def test_runtime_identity_is_the_authenticated_running_cpython_graph() -> None:
    graph = DependencyArtifactGraph.authenticate_stdlib_module("re")

    assert sys.implementation.name == "cpython"
    assert sys.version_info[:2] == (3, 12)
    assert graph.distribution_name == f"{sys.implementation.name}-stdlib"
    assert graph.distribution_version == sys.implementation.cache_tag
