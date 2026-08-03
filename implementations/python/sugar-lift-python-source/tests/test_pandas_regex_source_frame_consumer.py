from __future__ import annotations

import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
)
from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactAuthenticationError,
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import resolve_source_visible_frame
from sugar_lift_python_source.resolution_session import SourceResolutionSession


def _consumer_receipt(tmp_path: Path, filename: str, suffix: str = ""):
    source = (
        "from pandas._config.config import _select_options\n"
        "_select_options('display')\n"
        f"{suffix}"
    )
    path = tmp_path / filename
    path.write_text(source, encoding="utf-8")
    receipts, _ = authenticated_import_use_receipts(
        tmp_path,
        path,
        source,
        blake3_512_of(source.encode("utf-8")),
        module_identities={},
    )
    assert len(receipts) == 1
    return receipts[0]


def _coordinate_from_receipt(receipt) -> SourceFragmentCoordinateV1:
    site = receipt.use["useSite"]
    return SourceFragmentCoordinateV1(
        site["sourceCid"],
        site["startLine"],
        site["startCol"],
        site["endLine"],
        site["endCol"],
    )


def test_real_pandas_select_options_installs_authenticated_re_search_frame(
    tmp_path: Path,
) -> None:
    corpus = authenticated_pandas_corpus()
    assert corpus.file_count == 1421
    pandas_graph = DependencyArtifactGraph.authenticate(
        importlib.metadata.distribution("pandas")
    )
    regex_graph = DependencyArtifactGraph.authenticate_stdlib_module("re")
    receipt = _consumer_receipt(tmp_path, "truthful.py")
    session = SourceResolutionSession()
    resolved = resolve_import_binding(receipt, graph=pandas_graph, session=session)
    assert type(resolved) is ResolvedPythonObjectV1

    projected = resolve_source_visible_frame(
        resolved,
        graph=pandas_graph,
        dependency_graphs={"re": regex_graph},
        session=session,
    )

    assert isinstance(projected, tuple)
    frame, target = projected
    assert frame.owner is target
    assert target.name == "_select_options"
    nested_receipts, _ = authenticated_import_use_receipts(
        Path("."),
        Path(target.unit.filename),
        target.unit.source,
        target.unit.source_cid,
        module_identities={},
    )
    regex_receipts = tuple(
        item for item in nested_receipts if item.target_symbol == "python:re.search"
    )
    assert len(regex_receipts) == 1
    coordinate = _coordinate_from_receipt(regex_receipts[0])
    context = target.unit.construction_context
    parked = context.opaque_source_call_obligations.get(coordinate)
    assert coordinate in context.source_call_frames, (
        "authenticated pandas _select_options re.search consumer remained parked: "
        f"{getattr(parked, 'resolution_kind', None)}:"
        f"{getattr(parked, 'target_name', None)}"
    )
    nested_frame = context.source_call_frames[coordinate]
    assert coordinate not in context.opaque_source_call_obligations
    assert nested_frame.source_identity_cid == regex_graph.modules["re"].source_cid
    assert (
        nested_frame.definition_site.source_cid == regex_graph.modules["re"].source_cid
    )


def test_same_target_foreign_import_binding_cannot_reauthenticate_definition(
    tmp_path: Path,
) -> None:
    graph = DependencyArtifactGraph.authenticate(
        importlib.metadata.distribution("pandas")
    )
    truthful = _consumer_receipt(tmp_path, "truthful.py")
    foreign = _consumer_receipt(tmp_path, "foreign.py", "# foreign source occurrence\n")
    assert truthful.target_symbol == foreign.target_symbol
    assert truthful.import_binding.cid != foreign.import_binding.cid
    resolved = resolve_import_binding(truthful, graph=graph)
    foreign_resolved = resolve_import_binding(foreign, graph=graph)
    assert type(resolved) is ResolvedPythonObjectV1
    assert type(foreign_resolved) is ResolvedPythonObjectV1
    assert resolved.definition == foreign_resolved.definition
    assert resolved.source_cid == foreign_resolved.source_cid

    with pytest.raises(
        DependencyArtifactAuthenticationError,
        match="not byte-identical to artifact re-resolution",
    ):
        ResolvedPythonObjectV1.from_value(
            resolved.to_value(), graph=graph, authenticated_use=foreign
        )
