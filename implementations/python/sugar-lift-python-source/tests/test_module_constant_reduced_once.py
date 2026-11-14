"""A module constant is reduced once per module, and its halt is published.

Inventory item 29 (#7757, R5): a module-level constant was reduced once per
dependency frame, and a halt of its right-hand side (``X = 1 // 0``) was
dropped (``continue``), leaving the name a free symbolic read.  Now the
constants of a module are reduced once per session keyed on the module's
source, every frame reads that one result, and a halting constant is
published by name on the frame, where a call into the frame is that halt.
"""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.call_site_sugar import _frame_module_halt
from sugar_lift_python_source import manager_construction
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_lift_python_source.value_pins import scan_module_value_pins
from sugar_source_tree.backend import materialize
from sugar_source_tree.binding_state import (
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
)
from sugar_source_tree.reporter import NULL_REPORTER
from sugar_source_tree.tree import SourceFile

_SOURCE = "A = 1\nB = 1 // 0\nC = (2, 3)\ndef f():\n    return A\n"


def _materialized(tmp_path, monkeypatch):
    """One materialization of the module, as one dependency frame opens it."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mod.py").write_text(_SOURCE, encoding="utf-8")
    cid = blake3_512_of(_SOURCE.encode("utf-8"))
    reporter = ConstructionTestimonyReporterV1(
        NULL_REPORTER, SubstitutionTraceBuilderV1(cid)
    )
    source_file = SourceFile(
        (_SOURCE, "mod.py", cid),
        reporter=reporter,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    root = materialize(source_file.unit, source_file.root.ref, reporter)
    scan = scan_module_value_pins(
        source_file.root, source=_SOURCE, source_path="mod.py"
    )
    return root, scan, cid


def _counting_reductions(monkeypatch):
    counts = Counter()
    reduce = manager_construction._reduce_module_constant

    def counted(statement):
        counts[statement.targets[0].id] += 1
        return reduce(statement)

    monkeypatch.setattr(manager_construction, "_reduce_module_constant", counted)
    return counts


def test_each_constant_is_reduced_once_for_every_frame(tmp_path, monkeypatch):
    counts = _counting_reductions(monkeypatch)
    session = SourceResolutionSession(enrolled_distributions=frozenset())
    products = [
        manager_construction._session_module_constants(
            session, *_materialized(tmp_path, monkeypatch)
        )
        for _frame in range(3)
    ]
    assert counts == Counter({"A": 1, "B": 1, "C": 1})
    assert all(product is products[0] for product in products)


def test_a_raising_constant_halt_reaches_the_frame_result(tmp_path, monkeypatch):
    session = SourceResolutionSession(enrolled_distributions=frozenset())
    bindings, halts = manager_construction._session_module_constants(
        session, *_materialized(tmp_path, monkeypatch)
    )
    assert {binding.name for binding in bindings} == {"A", "C"}
    assert [halt.name for halt in halts] == ["B"]
    halt = halts[0].halt
    assert isinstance(halt, Incomplete)
    assert halt.effect.exception_name == "ZeroDivisionError"
    # A call into any frame of that module is the halt, never a free name.
    frame = SimpleNamespace(immutable_global_halts=halts)
    assert _frame_module_halt(frame) is halt
    assert _frame_module_halt(SimpleNamespace(immutable_global_halts=())) is None
