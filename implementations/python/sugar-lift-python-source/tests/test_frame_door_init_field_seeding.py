"""Plan Cut 6: the frame-door receiver must run __init__'s field stores.

Board 33995906761: pandas resource classes (ExcelFile/HDFStore/StataReader/
get_handle, ~320 sites) and contextlib.nullcontext derive their manager
receiver through the import/frame door, whose receiver ObjectValue is built
WITHOUT __init__'s field stores -- `self.r`/`self.result` is then undecided
at __enter__ (`enter-may-halt ObjectValue.attribute`).

Localized exactly (this session): ClassDefinitionValue
.construct_receiver_state_from_block is handed
- same-module path:   BlockValue[ReceiverFieldStoreValue]  -> fields {'r'}  (correct)
- import/frame-door:  BlockValue[ObjectValue(empty)]       -> fields {}     (bug)
i.e. `self.r = r`'s post_state reduces to a fresh empty ObjectValue instead of
a ReceiverFieldStoreValue, because the constructed-receiver coordinate minted
by ClassDef._source_visible_body is not matched on the frame-door path.

This test pins the DESIRED behavior; xfail(strict) so it flips to a failure
the moment the receiver seeds its field, forcing the pin to be removed.
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
from sugar_lift_python_source.manager_construction import construct_manager_behavior
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts


_BODY = (
    "class NC:\n"
    "    def __init__(self, r=None):\n"
    "        self.r = r\n"
    "    def __enter__(self):\n"
    "        return self.r\n"
    "    def __exit__(self, *e):\n"
    "        pass\n"
)


def _install(root: Path) -> importlib.metadata.Distribution:
    pkg = root / "seed_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from seed_pkg.impl import NC\n", encoding="utf-8")
    (pkg / "impl.py").write_text(_BODY, encoding="utf-8")
    meta = root / "seed_dist-1.0.dist-info"
    meta.mkdir()
    (meta / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: seed-dist\nVersion: 1.0\n", encoding="utf-8"
    )
    (meta / "top_level.txt").write_text("seed_pkg\n", encoding="utf-8")
    with (meta / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        w = csv.writer(stream)
        for item in (
            "seed_pkg/__init__.py",
            "seed_pkg/impl.py",
            "seed_dist-1.0.dist-info/METADATA",
            "seed_dist-1.0.dist-info/top_level.txt",
            "seed_dist-1.0.dist-info/RECORD",
        ):
            w.writerow((item, "", ""))
    sys.modules.pop("seed_pkg", None)
    sys.modules.pop("seed_pkg.impl", None)
    return importlib.metadata.Distribution.at(meta)


@pytest.mark.xfail(strict=True, reason="Cut 6: frame-door receiver drops __init__ field stores")
def test_import_backed_manager_receiver_runs_init_field_stores(tmp_path) -> None:
    dist = _install(tmp_path)
    graph = DependencyArtifactGraph.authenticate(dist)
    sys.path.insert(0, str(tmp_path))
    try:
        consumer = tmp_path / "use.py"
        source = "from seed_pkg import NC\n\ndef f():\n    with NC():\n        return 1\n"
        consumer.write_text(source, encoding="utf-8")
        receipts, _ = authenticated_import_use_receipts(
            tmp_path, consumer, source, blake3_512_of(source.encode()), module_identities={}
        )
        session = SourceResolutionSession(
            enrolled_distributions=frozenset({graph.distribution_name})
        )
        resolved = resolve_import_binding(receipts[0], graph=graph, session=session)
        assert isinstance(resolved, ResolvedPythonObjectV1)
        behavior = construct_manager_behavior(
            resolved, graph=graph, actuals=(), session=session
        )
        fields = {f.name for f in behavior.receiver_state.fields}
        assert "r" in fields, f"__init__ field store dropped on the frame door; got {fields}"
    finally:
        sys.path.remove(str(tmp_path))
