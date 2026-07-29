"""RED option: nested headers belong to the outer owner, bodies do not."""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path
import sys

from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import resolve_source_visible_frame
from sugar_lift_python_source.resolution_session import SourceResolutionSession


HEADER_CLASSES = (
    "NestedFunctionDecorator",
    "NestedFunctionDefault",
    "NestedFunctionAnnotation",
    "LambdaDefault",
    "NestedClassDecorator",
    "NestedClassBase",
    "NestedClassKeyword",
)
BODY_CLASSES = (
    "NestedFunctionBody",
    "LambdaBody",
    "NestedClassBody",
)


def _install_header_owner_distribution(
    root: Path,
) -> importlib.metadata.Distribution:
    package = root / "header_owner_pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from header_owner_pkg.implementation import selected\n",
        encoding="utf-8",
    )
    classes = "".join(
        f"@retain\nclass {name}:\n    token = {index}\n\n"
        for index, name in enumerate((*HEADER_CLASSES, *BODY_CLASSES), 1)
    )
    (package / "implementation.py").write_text(
        "def retain(value):\n"
        "    return value\n\n"
        + classes
        + "def selected(value):\n"
        "    @NestedFunctionDecorator\n"
        "    def nested_function(\n"
        "        argument: NestedFunctionAnnotation = NestedFunctionDefault,\n"
        "        factory=(lambda item=LambdaDefault: LambdaBody),\n"
        "    ):\n"
        "        NestedFunctionBody\n"
        "        return argument\n\n"
        "    @NestedClassDecorator\n"
        "    class NestedClass(NestedClassBase, metaclass=NestedClassKeyword):\n"
        "        body_only: NestedClassBody\n\n"
        "    return value\n",
        encoding="utf-8",
    )
    metadata = root / "header_owner_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: header-owner-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text(
        "header_owner_pkg\n", encoding="utf-8"
    )
    recorded = (
        "header_owner_pkg/__init__.py",
        "header_owner_pkg/implementation.py",
        "header_owner_dist-1.0.dist-info/METADATA",
        "header_owner_dist-1.0.dist-info/top_level.txt",
        "header_owner_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    sys.modules.pop("header_owner_pkg", None)
    sys.modules.pop("header_owner_pkg.implementation", None)
    return importlib.metadata.Distribution.at(metadata)


def _selected_frame(tmp_path: Path):
    distribution = _install_header_owner_distribution(tmp_path)
    graph = DependencyArtifactGraph.authenticate(distribution)
    consumer = tmp_path / "consumer.py"
    source = "import header_owner_pkg\nheader_owner_pkg.selected(1)\n"
    consumer.write_text(source, encoding="utf-8")
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
    assert frame.owner is target
    assert target.name == "selected"
    return frame


def test_nested_evaluated_headers_enroll_module_decorated_classes_for_outer_owner(
    tmp_path: Path,
) -> None:
    frame = _selected_frame(tmp_path)
    enrolled = tuple(binding.name for binding in frame.decorated_class_bindings)

    assert enrolled == HEADER_CLASSES
    assert all(
        binding.publication.final_class is binding.value.published_floor
        for binding in frame.decorated_class_bindings
    )


def test_nested_bodies_do_not_enroll_module_decorated_classes_for_outer_owner(
    tmp_path: Path,
) -> None:
    frame = _selected_frame(tmp_path)
    enrolled = {binding.name for binding in frame.decorated_class_bindings}

    assert enrolled.isdisjoint(BODY_CLASSES)
