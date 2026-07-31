"""Source call frames retain ordinary source-class globals used by isinstance."""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

from sugar_lift_py_tests.floor import ObjectMethodValue
from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import resolve_source_visible_frame


PROVIDER = (
    "class nonmember(object):\n"
    "    def __init__(self, value):\n"
    "        self.value = value\n"
    "def probe(value):\n"
    "    if isinstance(value, nonmember):\n"
    "        return value.value\n"
    "    return 2\n"
    "def locally_shadowed(value):\n"
    "    nonmember = value\n"
    "    return isinstance(value, nonmember)\n"
)


def _distribution(root: Path) -> importlib.metadata.Distribution:
    package = root / "instancecheck_fixture"
    package.mkdir()
    (package / "__init__.py").write_text(PROVIDER, encoding="utf-8")
    metadata = root / "instancecheck_fixture-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: instancecheck-fixture\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text(
        "instancecheck_fixture\n", encoding="utf-8"
    )
    recorded = (
        "instancecheck_fixture/__init__.py",
        "instancecheck_fixture-1.0.dist-info/METADATA",
        "instancecheck_fixture-1.0.dist-info/top_level.txt",
        "instancecheck_fixture-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _frame(tmp_path: Path, symbol: str):
    dist = _distribution(tmp_path)
    graph = DependencyArtifactGraph.authenticate(dist)
    consumer = tmp_path / "consumer.py"
    source = f"from instancecheck_fixture import {symbol}\n{symbol}(None)\n"
    consumer.write_text(source, encoding="utf-8")
    receipts, _ = authenticated_import_use_receipts(
        tmp_path,
        consumer,
        source,
        blake3_512_of(source.encode("utf-8")),
        module_identities={},
    )
    resolved = resolve_import_binding(receipts[0], graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    projected = resolve_source_visible_frame(resolved, graph=graph)
    assert isinstance(projected, tuple)
    frame, target = projected
    assert target.name == symbol
    return frame


def test_enum_nonmember_global_decides_object_method_false(tmp_path: Path) -> None:
    """The real false face reaches ``_is_descriptor``; it never reads `.value`."""
    frame = _frame(tmp_path, "probe")
    bindings = frame.source_class_bindings

    assert tuple(binding.name for binding in bindings) == ("nonmember",)
    nonmember = bindings[0].value
    assert nonmember.ordinary_instancecheck is True
    method = ObjectMethodValue(
        "member", ("self",), TrueBoolLiteralSugar(site="method-site")
    )

    outcome = nonmember.test_python_type(method, "Lib/enum.py:446:13")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, FalseBoolLiteralSugar)


def test_local_nonmember_shadow_cannot_borrow_module_class_authority(
    tmp_path: Path,
) -> None:
    """Lying arm: a local binding excludes the same-spelled module class."""
    frame = _frame(tmp_path, "locally_shadowed")

    assert all(
        binding.name != "nonmember" for binding in frame.source_class_bindings
    )
