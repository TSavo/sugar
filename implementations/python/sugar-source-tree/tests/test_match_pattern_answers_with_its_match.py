"""A ``case`` and its pattern answer the roll with their ``match`` (#7757).

``Match._construct_sugar`` consumes each case -- it builds the guard and the
body, which answer for themselves -- and reads each pattern structurally
(``_pattern_alternatives``, ``_pattern_spec``), building only the
expressions it holds.  Neither the case nor the pattern constructs as a
value, and nothing answered for a pattern: ``core/computation/parsing.py``
(``case "`":`` inside a ``while``, the corpus's one ``match``) ended in
``MatchValue registered but never answered the roll call`` on the pandas
board at ``d54a43717`` (run 43739300912).  Both are structural parts
(``_structural_part``) and answer where the match constructs.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import MatchCase, MatchValue, Pattern
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def test_a_case_and_its_pattern_are_structural_parts():
    assert MatchCase._structural_part
    assert Pattern._structural_part
    assert MatchValue._structural_part


def test_a_value_pattern_answers_with_its_match():
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(
        "def f(s):\n"
        "    i = 0\n"
        "    n = 0\n"
        "    while i < len(s):\n"
        "        match s[i]:\n"
        '            case "`":\n'
        "                n += 1\n"
        "                i += 1\n"
        "                continue\n"
        '            case "a" | "b":\n'
        "                n += 2\n"
        "        i += 1\n"
        "    return n\n"
    )
    f.close()
    report = discharge(
        SourceFile(
            path_source(f.name),
            reporter=CollectingReporter(),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )
    assert not [
        e
        for e in report.minority
        if e.kind in ("MatchCase", "MatchValue", "MatchOr")
    ], report.minority
