"""Publication-door laws for source-defined async generator managers.

Async lifecycle consumption is deliberately outside this module.  These tests
pin the publication boundary: direct and reaching-assignment ``AsyncWith``
calls are projected at their authenticated use occurrence, without borrowing
the synchronous ``With`` protocol.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerResolutionGapV1,
    SourceDerivedGeneratorResourceRefV1,
    TreeConstructionContextV1,
)
from sugar_lift_python_source.manager_summary_derivation import (
    _projected_manager_call_uses,
    populate_source_derived_resource_refs,
)
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _tree(source: str) -> SourceFile:
    context = TreeConstructionContextV1.for_source_call_construction()
    return SourceFile(
        (
            source,
            "async_manager_specimen.py",
            blake3_512_of(source.encode("utf-8")),
        ),
        construction_context=context,
    )


def test_direct_async_manager_call_enters_publication_projection():
    tree = _tree(
        "from resource_pkg import renamed_resource\n"
        "async def consume():\n"
        "    async with renamed_resource(1) as entered:\n"
        "        return entered\n"
    )

    projected = _projected_manager_call_uses(tree)

    assert len(projected) == 1
    coordinate, call, exit_face_id = next(iter(projected.values()))
    assert coordinate.source_cid == tree.unit.source_cid
    assert coordinate.start_line == 3
    assert call.kind == "Call"
    assert exit_face_id


def test_renamed_assigned_async_manager_stays_unprojected_without_async_substitution():
    tree = _tree(
        "from resource_pkg import first_resource as renamed_resource\n"
        "async def consume():\n"
        "    held = renamed_resource(1)\n"
        "    async with held as entered:\n"
        "        return entered\n"
    )

    projected = _projected_manager_call_uses(tree)

    assert projected == {}


def test_plain_async_manager_name_without_authenticated_call_stays_unprojected():
    tree = _tree(
        "async def consume(manager):\n"
        "    async with manager as entered:\n"
        "        return entered\n"
    )

    assert _projected_manager_call_uses(tree) == {}


def _async_distribution(root: Path):
    package = root / "resource_pkg"
    package.mkdir()
    files = {
        "__init__.py": "from resource_pkg.factory import renamed_resource\n",
        "factory.py": (
            "from resource_pkg.wrapper import resource_manager\n"
            "@resource_manager\n"
            "async def renamed_resource(value):\n"
            "    yield value\n"
        ),
        "wrapper.py": (
            "class AsyncResource:\n"
            "    def __init__(self, generator):\n"
            "        self.generator = generator\n"
            "    async def __aenter__(self):\n"
            "        return await self.generator.__anext__()\n"
            "    async def __aexit__(self, kind, value, traceback):\n"
            "        return False\n"
            "def resource_manager(function):\n"
            "    def helper(*args, **kwargs):\n"
            "        return AsyncResource(function(*args, **kwargs))\n"
            "    return helper\n"
        ),
    }
    for relative, source in files.items():
        (package / relative).write_text(source, encoding="utf-8")
    metadata = root / "resource_pkg_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: resource-pkg-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for relative in files:
            writer.writerow((f"resource_pkg/{relative}", "", ""))
        writer.writerow(("resource_pkg_dist-1.0.dist-info/METADATA", "", ""))
        writer.writerow(("resource_pkg_dist-1.0.dist-info/RECORD", "", ""))
    return importlib.metadata.Distribution.at(metadata)


def test_async_generator_without_async_frame_protocol_stays_typed_gap(tmp_path: Path):
    distribution = _async_distribution(tmp_path)
    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from resource_pkg import renamed_resource\n"
        "async def consume():\n"
        "    async with renamed_resource(1) as entered:\n"
        "        return entered\n",
        encoding="utf-8",
    )
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(path_source(str(consumer)), construction_context=context)

    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=consumer,
        distribution_index={"resource_pkg": distribution},
    )

    assert len(context.source_derived_contract_refs) == 1
    ref = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(ref, ContextManagerResolutionGapV1)
    assert not isinstance(ref, SourceDerivedGeneratorResourceRefV1)
    assert context.contract_refs.native_definitions == {}
