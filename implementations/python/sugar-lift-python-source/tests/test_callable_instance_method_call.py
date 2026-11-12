"""An imported ``name = Class()`` callable called from a method keeps its body."""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_lift_py_tests.outcome import Halted
from sugar_lift_py_tests.sugar.expr_statement_sugar import ExprStatementSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding as _resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import (
    _ExternalCallTargetGap,
    _call_coordinate,
    _local_named_calls,
    _resolve_external_call_frame,
    resolve_source_visible_frame,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.nodes import ClassDef, FunctionDef


_FAIL_ASSIGN = """class _Fail:
    def __call__(self, reason=""):
        raise RuntimeError(reason)


fail = _Fail()
"""

_FAIL_ANNASSIGN = """class _Fail:
    def __call__(self, reason=""):
        raise RuntimeError(reason)


fail: _Fail = _Fail()
"""

_MANAGER = """from arbitrary.support import fail


class RaisesExc:
    def __exit__(self, exc_type=None, exc_val=None, exc_tb=None):
        fail("DID NOT RAISE")
        return True
"""


_NESTED_FAIL_FACTORY = """from arbitrary.support import fail


class RaisesExc:
    def __init__(self, expected=None):
        self.expected_exceptions = expected
        self.match = None
    def __enter__(self):
        return self
    def __exit__(self, exc_type=None, exc_val=None, exc_tb=None):
        if exc_type is None:
            fail("DID NOT RAISE")
        return exc_type is self.expected_exceptions


def factory(expected=None):
    with RaisesExc(ValueError):
        raise ValueError("nested")
    return RaisesExc(expected)
"""


def _resolved_export(root: Path, *, manager_source: str, support_source: str, exported: str):
    graph = DependencyArtifactGraph.authenticate(
        _distribution(
            root,
            manager_source=manager_source,
            support_source=support_source,
            exported=exported,
        )
    )
    consumer = f"from arbitrary.manager import {exported}\n{exported}()\n"
    path = root / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode())
    receipts, _ = authenticated_import_use_receipts(root, path, consumer, source_cid)
    session = _session_enrolling_graph(graph)
    resolved = resolve_import_binding(receipts[0], graph=graph, session=session)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    return graph, resolved, session


def _session_enrolling_graph(graph):
    name = graph.distribution_name
    if not name:
        raise AssertionError("callable-instance graph test requires a distribution name")
    return SourceResolutionSession(enrolled_distributions=frozenset({name}))


def resolve_import_binding(*args, graph, session=None, **kwargs):
    if session is None:
        session = _session_enrolling_graph(graph)
    return _resolve_import_binding(*args, graph=graph, session=session, **kwargs)


def _distribution(
    root: Path, *, manager_source: str, support_source: str, exported: str = "RaisesExc"
):
    package = root / "arbitrary"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        f"from arbitrary.manager import {exported}\n", encoding="utf-8"
    )
    (package / "manager.py").write_text(manager_source, encoding="utf-8")
    (package / "support.py").write_text(support_source, encoding="utf-8")
    metadata = root / "arbitrary_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: arbitrary-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        "arbitrary/__init__.py",
        "arbitrary/manager.py",
        "arbitrary/support.py",
        "arbitrary_dist-1.0.dist-info/METADATA",
        "arbitrary_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _resolved_class(root: Path, *, support_source: str):
    graph = DependencyArtifactGraph.authenticate(
        _distribution(root, manager_source=_MANAGER, support_source=support_source)
    )
    consumer = "from arbitrary.manager import RaisesExc\nRaisesExc()\n"
    path = root / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode())
    receipts, _ = authenticated_import_use_receipts(root, path, consumer, source_cid)
    session = _session_enrolling_graph(graph)
    resolved = resolve_import_binding(receipts[0], graph=graph, session=session)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    return graph, resolved, session


@pytest.mark.parametrize("support_source", [_FAIL_ASSIGN, _FAIL_ANNASSIGN])
def test_external_call_frame_follows_callable_instance_export(tmp_path, support_source):
    graph, resolved, session = _resolved_class(tmp_path, support_source=support_source)
    frame = _resolve_external_call_frame(
        "fail", resolved=resolved, graph=graph, session=session
    )
    assert not isinstance(frame, _ExternalCallTargetGap)
    assert frame.parameters[0] == "reason"
    assert "__call__" in frame.owner.name or frame.owner.name == "__call__"


@pytest.mark.parametrize("support_source", [_FAIL_ASSIGN, _FAIL_ANNASSIGN])
def test_method_seats_imported_callable_instance_frame(tmp_path, support_source):
    graph, resolved, session = _resolved_class(tmp_path, support_source=support_source)
    frame, target = resolve_source_visible_frame(
        resolved, graph=graph, session=session
    )
    del frame
    exit_fn = next(
        item
        for item in target.body
        if isinstance(item, FunctionDef) and item.name == "__exit__"
    )
    fail_calls = [call for call in _local_named_calls(exit_fn) if call.func.id == "fail"]
    assert fail_calls
    context = target.unit.construction_context
    seated = context.source_call_frames[_call_coordinate(fail_calls[0])]
    assert seated is not None
    assert seated.parameters[0] == "reason"


@pytest.mark.parametrize("support_source", [_FAIL_ASSIGN, _FAIL_ANNASSIGN])
def test_method_fail_statement_halts_through_call(tmp_path, support_source):
    graph, resolved, session = _resolved_class(tmp_path, support_source=support_source)
    _frame, target = resolve_source_visible_frame(
        resolved, graph=graph, session=session
    )
    exit_fn = next(
        item
        for item in target.body
        if isinstance(item, FunctionDef) and item.name == "__exit__"
    )
    fail_call = next(call for call in _local_named_calls(exit_fn) if call.func.id == "fail")
    outcome = ExprStatementSugar(
        value=fail_call.sugar(), site=fail_call.fragment
    ).desugar()
    exits = getattr(outcome, "exits", None)
    if exits is None:
        assert isinstance(outcome, Halted)
        return
    assert any(isinstance(face, Halted) for face in exits)


def test_nested_imported_fail_publishes_on_the_units_own_context(tmp_path):
    """The frame door seats imported fail() before the nested derive, on the
    one context its unit was prepared under. Since #7801 nothing rebinds a
    unit's context, so there is no second, "live" table to publish onto."""
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExpectsModeV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
    )

    graph, resolved, session = _resolved_export(
        tmp_path,
        manager_source=_NESTED_FAIL_FACTORY,
        support_source=_FAIL_ASSIGN,
        exported="factory",
    )
    _frame, target = resolve_source_visible_frame(
        resolved, graph=graph, session=session
    )
    live = target.unit.construction_context
    raises_exc = next(
        item
        for item in (target.unit.module_direct_bindings or {}).get("RaisesExc", ())
        if isinstance(item, ClassDef)
    )
    exit_fn = next(
        item
        for item in raises_exc.body
        if isinstance(item, FunctionDef) and item.name == "__exit__"
    )
    fail_call = next(call for call in _local_named_calls(exit_fn) if call.func.id == "fail")
    seated = live.source_call_frames.get(_call_coordinate(fail_call))
    assert seated is not None
    assert seated.parameters[0] == "reason"
    reference = next(
        value
        for value in live.source_derived_contract_refs.values()
        if isinstance(value, SourceDerivedContextManagerRefV1)
    )
    assert isinstance(reference.semantics, EffectBoundarySemanticsV1)
    assert isinstance(reference.semantics.mode, ExpectsModeV1)
