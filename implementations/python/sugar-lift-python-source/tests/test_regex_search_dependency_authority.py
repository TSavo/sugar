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
    resolve_import_binding as _resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import (
    _seat_import_value_use_receipts,
    resolve_source_visible_frame as _resolve_source_visible_frame,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import Attribute, Call, FunctionDef
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.tree import SourceFile

SOURCE = (
    "import re\n"
    "def selected(subject):\n"
    '    return re.search("needle", subject, re.I)\n'
)


def _stdlib_session(*, enabled: bool = True) -> SourceResolutionSession:
    """CPython is cited across an authoritative empty enrolled population."""
    return SourceResolutionSession(enrolled_distributions=frozenset(), enabled=enabled)


def resolve_import_binding(*args, session=None, **kwargs):
    return _resolve_import_binding(
        *args, session=_stdlib_session() if session is None else session, **kwargs
    )


def resolve_source_visible_frame(*args, session=None, **kwargs):
    return _resolve_source_visible_frame(
        *args, session=_stdlib_session() if session is None else session, **kwargs
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
    assert frame.body.site.node is target
    assert frame.definition_site.source_cid == module.source_cid
    assert frame.definition_site.source_cid == resolved.definition.source_cid
    obligations = tuple(
        row
        for roster in (
            frame.owner.unit.construction_context.opaque_source_call_obligations.values()
        )
        for row in roster.obligations
    )
    warnings = tuple(
        item for item in obligations if item.target_name == "python:warnings.warn"
    )
    assert len(warnings) == 1
    relation = warnings[0].import_call_value_subsumption
    assert relation is not None
    calls, _ = authenticated_import_use_receipts(
        Path("."),
        Path(module.source_seat),
        module.source,
        module.source_cid,
        module_identities={},
    )
    values, _ = authenticated_import_value_use_receipts(
        Path("."),
        Path(module.source_seat),
        module.source,
        module.source_cid,
        module_identities={},
    )
    warnings_call = next(
        item
        for item in calls
        if item.target_symbol == "python:warnings.warn"
        and item.use["useSite"]["startLine"] == 302
    )
    warnings_value = next(
        item
        for item in values
        if item.target_symbol == "python:warnings.warn"
        and item.use["useSite"]["startLine"] == 302
    )
    from sugar_lift_python_source.canonical import cid_of_json

    assert relation.call_use_cid == warnings_call.use["cid"]
    assert relation.value_use_cid == warnings_value.use["cid"]
    assert relation.import_binding_cid == warnings_call.import_binding.cid
    assert relation.target_symbol == warnings_call.target_symbol
    assert relation.exported_member_path == tuple(
        warnings_value.use["exportedMemberPath"]
    )
    assert relation.module_identity_cid == cid_of_json(
        warnings_call.import_binding.value["target"]["moduleIdentity"]
    )
    assert relation.resolution_kind == warnings[0].resolution_kind
    assert relation.resolved_object_cid == warnings[0].resolved_object_cid
    context = frame.owner.unit.construction_context
    assert context is not None
    value_site = warnings_value.use["useSite"]
    value_span = (
        value_site["startLine"],
        value_site["startCol"],
        value_site["endLine"],
        value_site["endCol"],
    )
    assert frame.owner.unit.import_value_use_resolution(value_span) is None
    parked_before = dict(context.opaque_source_call_obligations)
    unrelated_rows = {
        key: row
        for key, row in context.source_import_value_receipts_by_site.items()
        if row is not warnings_value
    }
    assert unrelated_rows
    assert context.opaque_source_call_obligations == parked_before

    # The identical authenticated value receipt, when owned as a standalone
    # value occurrence rather than the Call.func subtree, follows ordinary
    # value seating and cannot borrow the parked Call's refusal.
    standalone = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        construction_context=context,
    )
    standalone_value = next(
        node
        for node in standalone.nodes()
        if isinstance(node, Attribute)
        and node.line_col_span().start_line == value_span[0]
        and node.line_col_span().start_col == value_span[1]
        and node.line_col_span().end_line == value_span[2]
        and node.line_col_span().end_col == value_span[3]
    )
    _seat_import_value_use_receipts(
        source_file=standalone,
        module=module,
        target=standalone_value,
        session=_stdlib_session(enabled=False),
        context=context,
        dependency_graphs={"re": graph},
    )
    assert standalone.unit.import_value_use_resolution(value_span) is warnings_value
    assert context.opaque_source_call_obligations == parked_before
    wrong_kind = (
        "call-graph-cycle"
        if warnings[0].resolution_kind != "call-graph-cycle"
        else "call-target-source-absent"
    )
    with pytest.raises(ValueError, match="cross-wired"):
        replace(warnings[0], resolution_kind=wrong_kind)
    with pytest.raises(ValueError, match="cross-wired"):
        replace(warnings[0], resolved_object_cid="blake3-512:" + "6" * 128)
    with pytest.raises(ValueError, match="producer authority"):
        replace(
            relation,
            call_coordinate=relation.callee_coordinate,
            callee_coordinate=relation.call_coordinate,
        )
    for change in (
        {"source_cid": "blake3-512:" + "0" * 128},
        {"module_identity_cid": "blake3-512:" + "1" * 128},
        {"import_binding_cid": "blake3-512:" + "2" * 128},
        {"target_symbol": "python:warnings.other"},
        {"exported_member_path": ("other",)},
        {"call_use_cid": "blake3-512:" + "3" * 128},
        {"value_use_cid": "blake3-512:" + "4" * 128},
        {"resolution_kind": "call-target-source-absent"},
        {"resolved_object_cid": "blake3-512:" + "6" * 128},
        {"call_coordinate": relation.callee_coordinate},
        {"callee_coordinate": relation.call_coordinate},
        {"relation_cid": "blake3-512:" + "5" * 128},
    ):
        with pytest.raises(ValueError, match="producer authority"):
            replace(relation, **change)
    assert {
        key: row
        for key, row in context.source_import_value_receipts_by_site.items()
        if row is not warnings_value
    } == unrelated_rows


def test_duplicate_identical_call_receipt_is_loud_before_pairing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    call, _ = _receipts(tmp_path)
    graph = DependencyArtifactGraph.authenticate_stdlib_module("re")
    resolved = resolve_import_binding(call, graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    import sugar_lift_py_tests.import_binding as import_binding

    original = import_binding.authenticated_import_use_receipts

    def duplicated(*args, **kwargs):
        receipts, outcomes = original(*args, **kwargs)
        return tuple(receipts) + tuple(receipts), outcomes

    monkeypatch.setattr(import_binding, "authenticated_import_use_receipts", duplicated)
    with pytest.raises(BackendDefect, match="duplicate authenticated call receipt CID"):
        resolve_source_visible_frame(
            resolved,
            graph=graph,
            session=_stdlib_session(enabled=False),
        )


def test_reversed_receipt_iteration_preserves_relation_cid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    call, _ = _receipts(tmp_path)
    graph = DependencyArtifactGraph.authenticate_stdlib_module("re")
    resolved = resolve_import_binding(call, graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)

    def relation_cid(projected) -> str:
        assert isinstance(projected, tuple)
        _, target = projected
        rows = tuple(
            row
            for roster in (
                target.unit.construction_context.opaque_source_call_obligations.values()
            )
            for row in roster.obligations
            if row.target_name == "python:warnings.warn"
        )
        assert len(rows) == 1
        relation = rows[0].import_call_value_subsumption
        assert relation is not None
        return relation.relation_cid

    ordinary = relation_cid(
        resolve_source_visible_frame(
            resolved, graph=graph, session=_stdlib_session(enabled=False)
        )
    )
    import sugar_lift_py_tests.import_binding as import_binding

    original_calls = import_binding.authenticated_import_use_receipts
    original_values = import_binding.authenticated_import_value_use_receipts

    def reversed_calls(*args, **kwargs):
        rows, outcomes = original_calls(*args, **kwargs)
        return tuple(reversed(rows)), outcomes

    def reversed_values(*args, **kwargs):
        rows, outcomes = original_values(*args, **kwargs)
        return tuple(reversed(rows)), outcomes

    monkeypatch.setattr(
        import_binding, "authenticated_import_use_receipts", reversed_calls
    )
    monkeypatch.setattr(
        import_binding,
        "authenticated_import_value_use_receipts",
        reversed_values,
    )
    reversed_cid = relation_cid(
        resolve_source_visible_frame(
            resolved, graph=graph, session=_stdlib_session(enabled=False)
        )
    )
    assert reversed_cid == ordinary


def test_alias_import_search_resolves_the_same_exact_stdlib_definition(
    tmp_path: Path,
) -> None:
    source = (
        "import re as regex\n"
        "def selected(subject):\n"
        '    return regex.search("needle", subject, regex.I)\n'
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
        'def selected(re, subject):\n    return re.search("x", subject)\n',
        're = object()\ndef selected(subject):\n    return re.search("x", subject)\n',
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
        session=_stdlib_session(),
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
