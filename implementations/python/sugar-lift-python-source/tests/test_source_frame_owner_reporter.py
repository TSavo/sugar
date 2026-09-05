"""The frame door seats a registering reporter, like the prefix door does.

#7423 made ``Call._construct_sugar`` retain the source-call-frame OWNER
(``CallSiteSugar.expected_source_call_frame_owner``) through
``retain_registered_node_from``.  The owner is read from the producer
module's bind-time roster (``unit.function_nodes``), which is born on
whatever reporter the door that opened that ``SourceFile`` passed.  The
prefix door (``_module_prefix_outcome``) passes its
``ConstructionTestimonyReporterV1``; the frame door
(``_resolve_source_visible_frame_uncached``) passed nothing, so the roster
was born on ``NULL_REPORTER`` and every retention refused with
``producer reporter owns no registration table`` -- 25 files on the
2026-09-05 recensus, the first board after #7423.

Truthful twin: a dependency frame's owner is registered on a
``ConstructionTestimonyReporterV1`` and a consumer call retains it.
Lying twin: an owner born on ``NULL_REPORTER`` still refuses -- the door is
the fix, not a relaxed retention.
"""

from __future__ import annotations

import csv
import importlib.metadata
import sys
from pathlib import Path

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import resolve_source_visible_frame
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_source_tree.binding_state import (
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
)
from sugar_source_tree.nodes import Call, ClassDef, FunctionDef, Name
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.reporter import CollectingReporter, NullReporter
from sugar_source_tree.tree import SourceFile


def _install(root: Path) -> importlib.metadata.Distribution:
    package = root / "frame_pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from frame_pkg.implementation import selected\n", encoding="utf-8"
    )
    (package / "implementation.py").write_text(
        "class Boom(ValueError):\n"
        "    pass\n"
        "\n"
        "def helper(value):\n"
        "    return value\n"
        "\n"
        "def selected(value):\n"
        "    if value < 0:\n"
        "        raise Boom(value)\n"
        "    return helper(value)\n",
        encoding="utf-8",
    )
    metadata = root / "frame_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: frame-dist\nVersion: 1.0\n", encoding="utf-8"
    )
    (metadata / "top_level.txt").write_text("frame_pkg\n", encoding="utf-8")
    recorded = (
        "frame_pkg/__init__.py",
        "frame_pkg/implementation.py",
        "frame_dist-1.0.dist-info/METADATA",
        "frame_dist-1.0.dist-info/top_level.txt",
        "frame_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    sys.modules.pop("frame_pkg", None)
    sys.modules.pop("frame_pkg.implementation", None)
    return importlib.metadata.Distribution.at(metadata)


def _dependency_frame(tmp_path: Path):
    graph = DependencyArtifactGraph.authenticate(_install(tmp_path))
    consumer = tmp_path / "consumer.py"
    source = "import frame_pkg\nframe_pkg.selected(1)\n"
    consumer.write_text(source, encoding="utf-8")
    receipts, _ = authenticated_import_use_receipts(
        tmp_path, consumer, source, blake3_512_of(source.encode("utf-8")), module_identities={}
    )
    assert len(receipts) == 1
    session = SourceResolutionSession(enrolled_distributions=frozenset({graph.distribution_name}))
    resolved = resolve_import_binding(receipts[0], graph=graph, session=session)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    projected = resolve_source_visible_frame(resolved, graph=graph, session=session)
    assert isinstance(projected, tuple), projected
    frame, target = projected
    return frame, target


def test_dependency_frame_owner_is_registered_on_a_testimony_reporter(tmp_path) -> None:
    """The bind-time roster the frame owner is read from carries a registering reporter."""
    frame, target = _dependency_frame(tmp_path)
    owner = frame.owner
    assert isinstance(owner, FunctionDef) and owner.name == "selected"
    assert type(owner.reporter) is ConstructionTestimonyReporterV1, type(owner.reporter)
    assert owner.reporter.materialized_node_for_ref(owner.ref) is owner
    # The projected target is the same registered occurrence, not a remint.
    assert target is owner


def test_consumer_retains_the_dependency_frame_owner(tmp_path) -> None:
    """What #7423's expected_source_call_frame_owner projection does at the call."""
    frame, _target = _dependency_frame(tmp_path)
    owner = frame.owner
    consumer = ConstructionTestimonyReporterV1(
        CollectingReporter(), SubstitutionTraceBuilderV1(owner.unit.source_cid)
    )
    retained = consumer.retain_registered_node_from(owner, owner.reporter)
    assert retained is owner
    assert consumer.materialized_node_for_ref(owner.ref) is owner


def test_an_owner_born_on_null_reporter_still_refuses(tmp_path) -> None:
    """Lying twin: the door is the repair, retention never relaxes."""
    frame, _target = _dependency_frame(tmp_path)
    owner = frame.owner
    consumer = ConstructionTestimonyReporterV1(
        CollectingReporter(), SubstitutionTraceBuilderV1(owner.unit.source_cid)
    )
    with pytest.raises(BackendDefect, match="owns no registration table"):
        consumer.retain_registered_node_from(owner, NullReporter())


def test_dependency_body_call_to_a_same_module_class_retains(tmp_path) -> None:
    """The recensus shape: ``raise Boom(value)`` inside the dependency body.

    ``Boom`` is a ClassDef, so it is never in ``function_nodes``; the call
    reaches it through ``module_direct_bindings`` -- the bind-time roster that
    carries the reporter of whoever opened this ``SourceFile`` first.  On the
    2026-09-05 board that was ``NULL_REPORTER`` at
    ``pandas/util/version/__init__.py:113`` (``class InvalidVersion``), 25 files.
    """
    frame, target = _dependency_frame(tmp_path)
    boom_call = next(
        node
        for node in target.walk()
        if isinstance(node, Call) and isinstance(node.func, Name) and node.func.id == "Boom"
    )
    sugar = boom_call.sugar()  # BackendDefect before the frame door seated its reporter
    definition = sugar.expected_definition_ref
    assert isinstance(definition, ClassDef) and definition.name == "Boom"
    assert type(definition.reporter) is ConstructionTestimonyReporterV1


def test_dependency_first_opened_on_null_reporter_still_registers(tmp_path) -> None:
    """The recensus order: an earlier file's resolution opened the dependency
    module on NULL_REPORTER (demand walk / plain from_path).  Process residency
    then hands the frame door that shell; its bind-time roster is the NULL
    shell unless the frame door seats its own reporter onto it."""
    graph_root = tmp_path
    frame, target = None, None
    # First opener: NULL_REPORTER, as SourceFile.from_path does.
    distribution_dir = graph_root / "frame_pkg"
    # _dependency_frame installs the package; install first, open, then resolve.
    dist = _install(graph_root)
    stale = SourceFile.from_path(distribution_dir / "implementation.py")
    assert type(stale.reporter) is NullReporter
    graph = DependencyArtifactGraph.authenticate(dist)
    consumer = tmp_path / "consumer.py"
    source = "import frame_pkg\nframe_pkg.selected(1)\n"
    consumer.write_text(source, encoding="utf-8")
    receipts, _ = authenticated_import_use_receipts(
        tmp_path, consumer, source, blake3_512_of(source.encode("utf-8")), module_identities={}
    )
    session = SourceResolutionSession(enrolled_distributions=frozenset({graph.distribution_name}))
    resolved = resolve_import_binding(receipts[0], graph=graph, session=session)
    projected = resolve_source_visible_frame(resolved, graph=graph, session=session)
    assert isinstance(projected, tuple), projected
    frame, target = projected
    boom_call = next(
        node
        for node in target.walk()
        if isinstance(node, Call) and isinstance(node.func, Name) and node.func.id == "Boom"
    )
    sugar = boom_call.sugar()
    definition = sugar.expected_definition_ref
    assert isinstance(definition, ClassDef) and definition.name == "Boom"
    assert type(definition.reporter) is ConstructionTestimonyReporterV1
    assert type(frame.owner.reporter) is ConstructionTestimonyReporterV1
