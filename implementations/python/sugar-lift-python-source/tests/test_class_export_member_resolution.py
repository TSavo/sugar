"""Resolve Class.method through an imported class export.

Vendor shape matched by pytest's RaisesExc.__enter__:
``from _pytest._code import ExceptionInfo`` then ``ExceptionInfo.for_later()``.
The binding names the class export; the extra Attribute segment is a method
on that class, not a nested module.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

from sugar_lift_py_tests.import_binding import authenticated_import_value_use_receipts
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    PythonObjectResolutionGapV1,
    ResolvedPythonObjectV1,
    resolve_import_binding as _resolve_import_binding,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession


def resolve_import_binding(*args, graph, session=None, **kwargs):
    if session is None:
        session = SourceResolutionSession(
            enrolled_distributions=frozenset({graph.distribution_name})
        )
    return _resolve_import_binding(*args, graph=graph, session=session, **kwargs)


def _graph(root: Path, package: str):
    holder = (
        f"# package {package}\n"
        "class Holder:\n"
        "    @classmethod\n"
        "    def for_later(cls):\n"
        "        return None\n"
    )
    source = (
        f"from .holder import Holder  # {package}\n"
        "ready = Holder.for_later()\n"
        "missing = Holder.absent()\n"
    )
    files = {
        f"{package}/__init__.py": source,
        f"{package}/holder.py": holder,
    }
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
    receipts, _ = authenticated_import_value_use_receipts(
        root, path, source, source_cid, module_identities={}
    )
    return graph, receipts


def _receipt(receipts, path: list[str]):
    return next(row for row in receipts if row.use["exportedMemberPath"] == path)


def test_imported_class_classmethod_resolves_to_class_body_definition(tmp_path: Path):
    graph, receipts = _graph(tmp_path, "holder_package")

    result = resolve_import_binding(_receipt(receipts, ["for_later"]), graph=graph)

    assert isinstance(result, ResolvedPythonObjectV1), result
    assert result.definition.kind == "function"
    assert result.definition.name == "for_later"
    assert result.module_name == "holder_package.holder"


def test_imported_class_absent_member_stays_outside_binding(tmp_path: Path):
    graph, receipts = _graph(tmp_path, "absent_member_package")

    result = resolve_import_binding(_receipt(receipts, ["absent"]), graph=graph)

    assert isinstance(result, PythonObjectResolutionGapV1), result
    assert result.kind == "target-outside-binding"
    assert result.exported_name == "absent"
    assert result.module_name == "absent_member_package.holder"
