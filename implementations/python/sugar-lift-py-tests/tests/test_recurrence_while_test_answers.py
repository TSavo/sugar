"""A ``while`` left to its recurrence constructs its test (#7757, #8416).

Since #8965 a live loop whose item leaves changed a name it does not carry
(a name a call in the body may rebind: ``remainder.pop(0)``) runs as its
recurrence, never in hand, and a ``while`` keeps no item runtime there.  The
recurrence's symbolic item evaluated the test only where it reads no binding
(#9019), so a test that reads one was constructed by nothing: the pandas
board (main scorecard, #8416) ended eleven otherwise-clean files in
``Constant``/``Name``/``EvaluationRef registered but never answered the roll
call`` at a ``while`` test (``io/html.py:513``, ``io/formats/css.py:369``,
``io/formats/excel.py:901``, ``core/reshape/reshape.py:513``,
``core/computation/parsing.py:167``, ...), and the test's halts were the
loop's by no path.

The symbolic item evaluates every ``while`` test before its body, as every
item does: the test is constructed with the loop, built or refused by name,
and each halt of it leaves the loop.  Its truth decides the item only where
it reads no binding; otherwise the item runs under the test's slot guard.
"""

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def _report(tmp_path, source: str):
    path = tmp_path / "recurrence_while_test.py"
    path.write_text(source)
    return discharge(
        SourceFile(
            path_source(str(path)),
            reporter=CollectingReporter(),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )


def _absent_on_line(report, line: int):
    return [e for e in report.minority if e.start_line == line]


def test_a_recurrence_while_test_answers_the_roll(tmp_path):
    # The shape of ``pandas/io/html.py:513``: the body's calls may rebind
    # ``remainder`` and ``texts``, so the loop runs as its recurrence.
    report = _report(
        tmp_path,
        "def rows(remainder, index):\n"
        "    texts = []\n"
        "    while remainder and remainder[0][0] <= index:\n"
        "        prev = remainder.pop(0)\n"
        "        texts.append(prev)\n"
        "    return texts\n",
    )
    assert not _absent_on_line(report, 3), report.minority


def test_a_recurrence_while_over_a_constant_compare_answers_the_roll(tmp_path):
    # The shape of ``pandas/io/formats/css.py:369``.
    report = _report(
        tmp_path,
        "def size(unit, conversions):\n"
        "    seen = []\n"
        "    while unit != 'pt':\n"
        "        seen.append(unit)\n"
        "        unit = conversions.get(unit, 'pt')\n"
        "    return seen\n",
    )
    assert not _absent_on_line(report, 3), report.minority


def test_a_recurrence_while_over_a_builtin_call_answers_the_roll(tmp_path):
    # The shape of ``pandas/core/computation/parsing.py:167``.
    report = _report(
        tmp_path,
        "def scan(s, out):\n"
        "    i = 0\n"
        "    while i < len(s):\n"
        "        out.append(s[i])\n"
        "        i += 1\n"
        "    return out\n",
    )
    assert not _absent_on_line(report, 3), report.minority
