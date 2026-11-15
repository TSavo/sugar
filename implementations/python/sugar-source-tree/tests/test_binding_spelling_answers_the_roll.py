"""A binding target answers the roll where its binder constructs (#7757).

``__all__ = [...]`` constructs ``AssignSugar(name="__all__", ...)``: the
statement binds through its target Name and constructs nothing of it, and
``class C:`` binds through its parser-owned name occurrence
(``ClassDef.binding_target``) the same way.  Each such Name registered on the
roll when the tree was materialized and nothing answered for it, so every
pandas file with a module-level assignment or class had a silent absentee
(the board's ``UnaccountedConstruction`` after #8349).  The binder's
construction answers for each binding spelling by the one discharge of a node
a construction absorbs without constructing it.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def _report(src: str):
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(src)
    f.close()
    reporter = CollectingReporter()
    source_file = SourceFile(
        path_source(f.name),
        reporter=reporter,
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    return discharge(source_file), reporter


def _coordinates(entries, kind):
    return {(e.start_line, e.start_col) for e in entries if e.kind == kind}


def test_a_module_assignment_target_answers_where_the_assignment_constructs():
    report, reporter = _report('__all__ = ["a"]\nx = 1\n')
    assert reporter.gaps == []
    assert {(1, 0), (2, 0)} <= _coordinates(report.present, "Name")
    assert _coordinates(report.minority, "Name") == set()


def test_a_class_name_occurrence_answers_where_the_class_constructs():
    report, reporter = _report("class C:\n    pass\n")
    assert reporter.gaps == []
    assert (1, 6) in _coordinates(report.present, "Name")
    assert _coordinates(report.minority, "Name") == set()
