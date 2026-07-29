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
from sugar_lift_python_source.manager_construction import (
    _construct_reachable_decorated_class_bindings,
    resolve_source_visible_frame,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_source_tree.nodes import ClassDef, FunctionDef, SourceUnit
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


def test_backend_module_construction_receipt_discriminates_foreign_source(
    tmp_path: Path, monkeypatch
) -> None:
    truthful = _tree(tmp_path, monkeypatch)
    foreign_path = Path("foreign_decorated_module.py")
    foreign_path.write_text(
        "def replace(raw):\n    return raw\n\n"
        "@replace\nclass Original:\n    token = 8\n",
        encoding="utf-8",
    )
    foreign = SourceFile.from_path(
        foreign_path,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )

    assert truthful.unit.source_cid != foreign.unit.source_cid
    assert truthful.construction_event_receipt_cid != foreign.construction_event_receipt_cid


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
        "@replace\n"
        "class Unreachable:\n"
        "    stale = 2\n"
        "\n"
        "def shadowed(value):\n"
        "    Original = value\n"
        "    return isinstance(value, Original)\n"
        "\n"
        "def worker(value):\n"
        "    return isinstance(value, Original)\n"
        "\n"
        "def misleading(value):\n"
        "    global Unreachable\n"
        "    Unreachable = value\n"
        "    def nested():\n"
        "        return Unreachable\n"
        "    return value\n"
        "\n"
        "def selected(value):\n"
        "    def unrelated(frame: FrameType):\n"
        "        return frame\n"
        "    marker = int(misleading(value))\n"
        "    return worker(marker)\n",
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


def _install_admission_fixture(root: Path) -> importlib.metadata.Distribution:
    package = root / "admission_pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from admission_pkg.implementation import body_selected, selected\n",
        encoding="utf-8",
    )
    (package / "implementation.py").write_text(
        "from types import FrameType\n"
        "\n"
        "class Dependency:\n"
        "    token = 7\n"
        "\n"
        "def retain(raw):\n"
        "    int\n"
        "    FrameType\n"
        "    Dependency\n"
        "    return raw\n"
        "\n"
        "def locally_shadowed_retain(raw):\n"
        "    Dependency = raw\n"
        "    int\n"
        "    FrameType\n"
        "    return raw\n"
        "\n"
        "@locally_shadowed_retain\n"
        "@retain\n"
        "class Decorated:\n"
        "    token = 11\n"
        "\n"
        "@retain\n"
        "class BodyOnly:\n"
        "    token = 17\n"
        "\n"
        "@retain\n"
        "class StoreOnly:\n"
        "    token = 13\n"
        "\n"
        "def global_worker(value):\n"
        "    int\n"
        "    FrameType\n"
        "    Decorated\n"
        "    def nested(header: BodyOnly = BodyOnly):\n"
        "        return BodyOnly\n"
        "    return value\n"
        "\n"
        "def shadowed_worker(value):\n"
        "    Decorated = value\n"
        "    int\n"
        "    FrameType\n"
        "    return value\n"
        "\n"
        "def body_worker(value):\n"
        "    def nested():\n"
        "        return BodyOnly\n"
        "    return value\n"
        "\n"
        "def body_selected(value):\n"
        "    return body_worker(value)\n"
        "\n"
        "def store_and_load_worker(value):\n"
        "    StoreOnly = value\n"
        "    Decorated\n"
        "    return value\n"
        "\n"
        "def selected(value):\n"
        "    global_worker(value)\n"
        "    store_and_load_worker(value)\n"
        "    return shadowed_worker(value)\n",
        encoding="utf-8",
    )
    metadata = root / "admission_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: admission-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text("admission_pkg\n", encoding="utf-8")
    recorded = (
        "admission_pkg/__init__.py",
        "admission_pkg/implementation.py",
        "admission_dist-1.0.dist-info/METADATA",
        "admission_dist-1.0.dist-info/top_level.txt",
        "admission_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    sys.modules.pop("admission_pkg", None)
    sys.modules.pop("admission_pkg.implementation", None)
    return importlib.metadata.Distribution.at(metadata)


def test_reachable_decorated_class_admission_filters_before_symtable_contact(
    tmp_path: Path,
) -> None:
    distribution = _install_admission_fixture(tmp_path)
    graph = DependencyArtifactGraph.authenticate(distribution)
    consumer = tmp_path / "consumer.py"
    source = "import admission_pkg\nadmission_pkg.selected(1)\n"
    consumer.write_text(source, encoding="utf-8")
    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts

    receipts, _ = authenticated_import_use_receipts(
        tmp_path,
        consumer,
        source,
        blake3_512_of(source.encode("utf-8")),
        module_identities={},
    )
    session = SourceResolutionSession()
    resolved = resolve_import_binding(receipts[0], graph=graph, session=session)
    assert isinstance(resolved, ResolvedPythonObjectV1)

    contacted: list[tuple[str, str]] = []
    original_function_symtable = SourceUnit.function_symtable

    class _ObservedSymtable:
        def __init__(self, owner: str, table) -> None:
            self._owner = owner
            self._table = table

        def lookup(self, name: str):
            contacted.append((self._owner, name))
            try:
                return self._table.lookup(name)
            except KeyError:
                class _AbsentSymbol:
                    @staticmethod
                    def is_global() -> bool:
                        return False

                return _AbsentSymbol()

        def __getattr__(self, name: str):
            return getattr(self._table, name)

    def observed_function_symtable(self, name: str, lineno: int):
        return _ObservedSymtable(
            name, original_function_symtable(self, name, lineno)
        )

    monkeypatch.setattr(SourceUnit, "function_symtable", observed_function_symtable)

    projected = resolve_source_visible_frame(resolved, graph=graph, session=session)

    assert isinstance(projected, tuple)
    frame, target = projected
    assert target.name == "selected"
    assert tuple(binding.name for binding in frame.decorated_class_bindings) == (
        "Decorated",
        "BodyOnly",
    )
    body_source = "import admission_pkg\nadmission_pkg.body_selected(1)\n"
    body_consumer = tmp_path / "body_consumer.py"
    body_consumer.write_text(body_source, encoding="utf-8")
    body_receipts, _ = authenticated_import_use_receipts(
        tmp_path,
        body_consumer,
        body_source,
        blake3_512_of(body_source.encode("utf-8")),
        module_identities={},
    )
    body_session = SourceResolutionSession()
    body_resolved = resolve_import_binding(
        body_receipts[0], graph=graph, session=body_session
    )
    body_projected = resolve_source_visible_frame(
        body_resolved, graph=graph, session=body_session
    )
    assert isinstance(body_projected, tuple)
    body_frame, _ = body_projected
    assert all(
        binding.name != "BodyOnly"
        for binding in body_frame.decorated_class_bindings
    )
    assert ("global_worker", "Decorated") in contacted
    assert ("shadowed_worker", "Decorated") in contacted
    assert ("store_and_load_worker", "StoreOnly") in contacted
    assert ("store_and_load_worker", "Decorated") in contacted
    assert ("retain", "Dependency") in contacted
    assert ("locally_shadowed_retain", "Dependency") in contacted
    assert all(name not in {"int", "FrameType"} for _, name in contacted)


def test_nested_definition_headers_belong_to_outer_admission_owner(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "nested_headers.py"
    path.write_text(
        "def retain(raw):\n"
        "    return raw\n"
        "\n"
        "@retain\n"
        "class HeaderDecorated:\n"
        "    token = 19\n"
        "\n"
        "def nested_header_worker(value):\n"
        "    @HeaderDecorated\n"
        "    def nested_function(arg: HeaderDecorated = HeaderDecorated) -> HeaderDecorated:\n"
        "        return HeaderDecorated\n"
        "    @HeaderDecorated\n"
        "    async def nested_async_function(arg: HeaderDecorated = HeaderDecorated) -> HeaderDecorated:\n"
        "        return HeaderDecorated\n"
        "    @HeaderDecorated\n"
        "    class NestedClass(HeaderDecorated, metaclass=HeaderDecorated):\n"
        "        token = HeaderDecorated\n"
        "    nested_lambda = lambda arg=HeaderDecorated: HeaderDecorated\n"
        "    return value\n"
        "\n"
        "def selected(value):\n"
        "    return nested_header_worker(value)\n",
        encoding="utf-8",
    )
    tree = SourceFile.from_path(
        path,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    definitions = {
        item.name: item
        for item in tree.root.body
        if isinstance(item, (FunctionDef, ClassDef))
    }
    retain = definitions["retain"]
    selected = definitions["selected"]
    worker = definitions["nested_header_worker"]
    contacted: list[tuple[str, str]] = []
    original_function_symtable = SourceUnit.function_symtable

    class _ObservedSymtable:
        def __init__(self, owner: str, table) -> None:
            self._owner = owner
            self._table = table

        def lookup(self, name: str):
            contacted.append((self._owner, name))
            try:
                return self._table.lookup(name)
            except KeyError:
                class _AbsentSymbol:
                    @staticmethod
                    def is_global() -> bool:
                        return False

                return _AbsentSymbol()

        def __getattr__(self, name: str):
            return getattr(self._table, name)

    def observed_function_symtable(self, name: str, lineno: int):
        return _ObservedSymtable(
            name, original_function_symtable(self, name, lineno)
        )

    monkeypatch.setattr(SourceUnit, "function_symtable", observed_function_symtable)

    bindings = _construct_reachable_decorated_class_bindings(
        source_file=tree,
        target=selected,
        module_definitions=tuple(tree.root.body),
        reachable_definitions=(worker,),
        frames={"retain": retain.source_visible_call_frame()},
    )

    assert tuple(binding.name for binding in bindings) == ("HeaderDecorated",)
    # Twelve header occurrences execute in the outer function's scope. The four
    # same-name nested body occurrences belong to their nested owners.
    assert contacted.count(("nested_header_worker", "HeaderDecorated")) == 12


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
    original = next(
        item
        for item in target.unit.constructed_module.root.body
        if isinstance(item, ClassDef) and item.name == "Original"
    )
    sugar = original.sugar()
    assert binding.publication.binding_occurrence == sugar.binding_target_occurrence
    assert len(binding.publication.decorator_applications) == 2
    first, second = binding.publication.decorator_applications
    assert first.occurrence == sugar.decorator_occurrences[1]
    assert second.occurrence == sugar.decorator_occurrences[0]
    assert first.input_floor is binding.publication.raw_class
    assert second.input_floor is first.output_floor
    assert second.output_floor is binding.publication.final_class
    assert binding.publication.final_class.class_name == "Replacement"
    assert tuple(
        field.name for field in binding.publication.final_class.class_fields
    ) == ("token",)
    assert binding.publication.raw_class.class_name == "Original"
    assert tuple(field.name for field in binding.publication.raw_class.class_fields) == (
        "stale",
    )
