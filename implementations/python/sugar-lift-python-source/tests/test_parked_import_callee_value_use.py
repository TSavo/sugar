"""The callee of a parked imported call is one occurrence, cited once (#7723).

``os.environ.get("TZ")`` inside an authenticated definition carries two
lexical receipts for the same occurrence: the call receipt at the Call span
and the value receipt at its callee Attribute span.  ``environ`` is a
module-level instance of ``os``, so neither resolves to a definition through
the import binding (``target-outside-binding``).  The call door cites the
call opaque (``call-target-source-absent``, two-faced: completes or may
raise anything).  The value door used to run first and refuse the callee
before the call door had parked it, so ``pandas._testing.set_timezone`` and
``pandas.io.parsers.read_csv`` (``parser_defaults.items()``) were refused for
an occurrence the call door cites.

Fixture source is neutral and written for this test.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.import_binding import (
    authenticated_import_use_receipts,
    authenticated_import_value_use_receipts,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import (
    resolve_source_visible_frame,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession


def _resolved(root: Path, manager_source: str):
    package = root / "arbitrary"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "from arbitrary.manager import make_guard\n", encoding="utf-8"
    )
    (package / "manager.py").write_text(manager_source, encoding="utf-8")
    metadata = root / "arbitrary_dist-1.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: arbitrary-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    names = [
        "arbitrary/__init__.py",
        "arbitrary/manager.py",
        "arbitrary_dist-1.0.dist-info/METADATA",
        "arbitrary_dist-1.0.dist-info/RECORD",
    ]
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for name in names:
            writer.writerow((name, "", ""))
    graph = DependencyArtifactGraph.authenticate(
        importlib.metadata.Distribution.at(metadata)
    )
    session = SourceResolutionSession(
        enrolled_distributions=frozenset({graph.distribution_name})
    )
    consumer = "import arbitrary\narbitrary.make_guard(23)\n"
    path = root / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    receipts, _ = authenticated_import_use_receipts(
        root, path, consumer, blake3_512_of(consumer.encode())
    )
    resolved = resolve_import_binding(receipts[0], graph=graph, session=session)
    assert isinstance(resolved, ResolvedPythonObjectV1), resolved
    return resolved, graph, session


def _manager_receipts(graph, target_symbol: str):
    module = graph.modules["arbitrary.manager"]
    calls, _ = authenticated_import_use_receipts(
        Path("."),
        Path(module.source_seat),
        module.source,
        module.source_cid,
        module_identities={},
    )
    values, _ = authenticated_import_value_use_receipts(
        Path("."),
        Path(module.source_seat),
        module.source,
        module.source_cid,
        module_identities={},
    )
    return (
        [row for row in calls if row.target_symbol == target_symbol],
        [row for row in values if row.target_symbol == target_symbol],
    )


def test_parked_imported_callee_is_cited_at_the_call_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Truthful: the frame projects; the one occurrence is the call door's
    opaque citation, paired with its value receipt, and that value receipt is
    left unseated.  Before #7723 this raised ImportValueUseResolutionGap
    (target-outside-binding for python:os.environ.get)."""
    monkeypatch.chdir(tmp_path)
    source = (
        "import os\n"
        "def make_guard(expected):\n"
        '    return os.environ.get("TZ")\n'
    )
    resolved, graph, session = _resolved(tmp_path, source)

    projected = resolve_source_visible_frame(resolved, graph=graph, session=session)

    assert isinstance(projected, tuple), projected
    frame, _target = projected
    context = frame.owner.unit.construction_context
    calls, values = _manager_receipts(graph, "python:os.environ.get")
    assert len(calls) == 1 and len(values) == 1
    call_site = calls[0].use["useSite"]
    parked = [
        row
        for roster in context.opaque_source_call_obligations.values()
        for row in roster.obligations
        if row.target_name == "python:os.environ.get"
    ]
    assert len(parked) == 1
    obligation = parked[0]
    assert obligation.resolution_kind == "call-target-source-absent"
    assert (
        obligation.coordinate.start_line,
        obligation.coordinate.start_col,
        obligation.coordinate.end_line,
        obligation.coordinate.end_col,
    ) == (
        call_site["startLine"],
        call_site["startCol"],
        call_site["endLine"],
        call_site["endCol"],
    )
    relation = obligation.import_call_value_subsumption
    assert relation is not None
    assert relation.value_use_cid == values[0].use["cid"]
    value_site = values[0].use["useSite"]
    assert (
        frame.owner.unit.import_value_use_resolution(
            (
                value_site["startLine"],
                value_site["startCol"],
                value_site["endLine"],
                value_site["endCol"],
            )
        )
        is None
    )


def test_unresolved_value_use_that_is_no_callee_still_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lying: the same unresolved member read as a value (bound, then called
    through a local) has no parked call owning it.  It stays the named gap;
    the call door's citation is not borrowed by a neighbouring occurrence."""
    from sugar_source_tree.panic import ImportValueUseResolutionGap

    monkeypatch.chdir(tmp_path)
    source = (
        "import os\n"
        "def make_guard(expected):\n"
        "    getter = os.environ.get\n"
        '    return getter("TZ")\n'
    )
    resolved, graph, session = _resolved(tmp_path, source)

    with pytest.raises(ImportValueUseResolutionGap) as raised:
        resolve_source_visible_frame(resolved, graph=graph, session=session)

    assert "target-outside-binding" in raised.value.observed
    assert "'python:os.environ.get'" in raised.value.observed
