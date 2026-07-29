from __future__ import annotations

from pathlib import Path
import csv
import importlib.metadata
import sys

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import resolve_source_visible_frame
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


def _tree(tmp_path: Path, monkeypatch) -> SourceFile:
    monkeypatch.chdir(tmp_path)
    path = Path("decorated_module.py")
    path.write_text(
        "def replace(raw):\n"
        "    return raw\n"
        "\n"
        "@replace\n"
        "class Original:\n"
        "    token = 7\n"
    )
    return SourceFile.from_path(
        path,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def test_backend_module_construction_owns_a_stable_receipt_cid(
    tmp_path: Path, monkeypatch
) -> None:
    tree = _tree(tmp_path, monkeypatch)

    receipt = tree.root.unit.constructed_module.construction_event_receipt

    assert receipt.source_cid == tree.root.unit.source_cid
    assert isinstance(receipt.construction_event_receipt_cid, str)
    assert receipt.construction_event_receipt_cid
    assert tree.construction_event_receipt_cid == receipt.construction_event_receipt_cid
    assert (
        tree.constructed_module.construction_event_receipt_cid
        == receipt.construction_event_receipt_cid
    )


def test_class_definition_carries_ordered_decorator_sugars_and_occurrences(
    tmp_path: Path, monkeypatch
) -> None:
    tree = _tree(tmp_path, monkeypatch)
    definition = next(item for item in tree.root.body if isinstance(item, ClassDef))

    sugar = definition.sugar()

    assert len(sugar.decorator_sugars) == 1
    assert len(sugar.decorator_occurrences) == 1
    assert sugar.binding_target_occurrence == SourceFragmentCoordinateV1(
        tree.root.unit.source_cid,
        definition.binding_target.line_col_span().start_line,
        definition.binding_target.line_col_span().start_col,
        definition.binding_target.line_col_span().end_line,
        definition.binding_target.line_col_span().end_col,
    )
    occurrence = sugar.decorator_occurrences[0]
    assert type(occurrence) is SourceFragmentCoordinateV1
    assert occurrence.source_cid == tree.root.unit.source_cid
    assert occurrence == SourceFragmentCoordinateV1(
        tree.root.unit.source_cid,
        definition.decorators[0].line_col_span().start_line,
        definition.decorators[0].line_col_span().start_col,
        definition.decorators[0].line_col_span().end_line,
        definition.decorators[0].line_col_span().end_col,
    )


def _install(root: Path) -> importlib.metadata.Distribution:
    package = root / "decorated_pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from decorated_pkg.implementation import selected\n", encoding="utf-8"
    )
    (package / "implementation.py").write_text(
        "class Replacement:\n"
        "    token = 7\n"
        "\n"
        "def replace(raw):\n"
        "    return Replacement\n"
        "\n"
        "def retain(value):\n"
        "    return value\n"
        "\n"
        "@retain\n"
        "@replace\n"
        "class Original:\n"
        "    stale = 1\n"
        "\n"
        "def selected(value):\n"
        "    return isinstance(value, Original)\n",
        encoding="utf-8",
    )
    metadata = root / "decorated_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: decorated-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text("decorated_pkg\n", encoding="utf-8")
    recorded = (
        "decorated_pkg/__init__.py",
        "decorated_pkg/implementation.py",
        "decorated_dist-1.0.dist-info/METADATA",
        "decorated_dist-1.0.dist-info/top_level.txt",
        "decorated_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    sys.modules.pop("decorated_pkg", None)
    sys.modules.pop("decorated_pkg.implementation", None)
    return importlib.metadata.Distribution.at(metadata)


def test_reachable_decorated_class_publication_is_attached_to_selected_frame(
    tmp_path: Path,
) -> None:
    distribution = _install(tmp_path)
    graph = DependencyArtifactGraph.authenticate(distribution)
    consumer = tmp_path / "consumer.py"
    source = "import decorated_pkg\ndecorated_pkg.selected(1)\n"
    consumer.write_text(source, encoding="utf-8")
    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts

    receipts, _ = authenticated_import_use_receipts(
        tmp_path,
        consumer,
        source,
        blake3_512_of(source.encode("utf-8")),
        module_identities={},
    )
    assert len(receipts) == 1
    session = SourceResolutionSession()
    resolved = resolve_import_binding(receipts[0], graph=graph, session=session)
    assert isinstance(resolved, ResolvedPythonObjectV1)

    projected = resolve_source_visible_frame(resolved, graph=graph, session=session)

    assert isinstance(projected, tuple)
    frame, target = projected
    assert target.name == "selected"
    assert len(frame.decorated_class_bindings) == 1
    binding = frame.decorated_class_bindings[0]
    assert binding.name == "Original"
    assert binding.publication.module_construction_receipt_cid == (
        target.unit.constructed_module.construction_event_receipt_cid
    )
    assert binding.value.publication is binding.publication
    assert binding.value.published_floor is binding.publication.final_class
    assert binding.publication.final_class is not binding.publication.raw_class
