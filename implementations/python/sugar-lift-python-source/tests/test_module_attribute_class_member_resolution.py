"""``mod.Class.method`` resolves through the class body like ``Class.method``.

#7463 resolved ``from mod import Class`` then ``Class.method`` through the
class body.  The other two spellings of the same reference stayed
``target-outside-binding``:
- ``import mod`` then ``mod.Class.method``;
- ``from pkg import mod`` then ``mod.Class.method``.
pandas' ``get_handle`` calls ``tarfile.TarFile.open(...)``, so every
``with get_handle(...)`` (e.g. ``io/pickle.py:119``) refused at that receipt.
The class is resolved by the one export door and the method is looked up in
its own class body.  A member that the class body does not define stays
outside the binding.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.import_binding import authenticated_import_value_use_receipts
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    PythonObjectResolutionGapV1,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession

_HOLDER = (
    "class Holder:\n"
    "    @classmethod\n"
    "    def for_later(cls):\n"
    "        return None\n"
)


def _graph(root: Path, package: str, consumer: str):
    files = {
        f"{package}/__init__.py": f"# package {package}\n",
        f"{package}/holder.py": _HOLDER,
        f"{package}/user.py": consumer.format(package=package),
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    metadata = root / f"{package}_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {package}\nVersion: 1.0\n", encoding="utf-8"
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
    source = files[f"{package}/user.py"]
    receipts, _ = authenticated_import_value_use_receipts(
        root,
        root / package / "user.py",
        source,
        blake3_512_of(source.encode("utf-8")),
        module_identities={},
    )
    return graph, receipts


def _resolve(graph, receipts, path):
    receipt = next(row for row in receipts if row.use["exportedMemberPath"] == path)
    return resolve_import_binding(
        receipt,
        graph=graph,
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({graph.distribution_name})
        ),
    )


_SPELLINGS = [
    (
        "import_module",
        "import {package}.holder as holder\n"
        "ready = holder.Holder.for_later()\nmissing = holder.Holder.absent()\n",
        ["Holder", "for_later"],
        ["Holder", "absent"],
    ),
    (
        "from_package_import_module",
        "from {package} import holder\n"
        "ready = holder.Holder.for_later()\nmissing = holder.Holder.absent()\n",
        ["Holder", "for_later"],
        ["Holder", "absent"],
    ),
]


@pytest.mark.parametrize(("label", "consumer", "present", "absent"), _SPELLINGS)
def test_module_attribute_classmethod_resolves_to_class_body(
    tmp_path, label, consumer, present, absent
):
    graph, receipts = _graph(tmp_path, f"pkg_{label}", consumer)
    result = _resolve(graph, receipts, present)
    assert isinstance(result, ResolvedPythonObjectV1), result
    assert (result.definition.kind, result.definition.name) == ("function", "for_later")
    assert result.module_name == f"pkg_{label}.holder"


@pytest.mark.parametrize(("label", "consumer", "present", "absent"), _SPELLINGS)
def test_a_member_the_class_body_lacks_stays_outside_binding(
    tmp_path, label, consumer, present, absent
):
    graph, receipts = _graph(tmp_path, f"gap_{label}", consumer)
    result = _resolve(graph, receipts, absent)
    assert isinstance(result, PythonObjectResolutionGapV1), result
    assert result.kind == "target-outside-binding"
