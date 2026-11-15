"""Every decorator expression is built where its ``def`` statement runs (#7757).

Python evaluates a ``def``'s decorator expressions when the statement runs,
whatever applies their values afterwards.  A class-body method's decorators
(the class body's descriptor table applies them) and a ``contextmanager``
generator's (its call applies its own frame) were built by nothing, so
their nodes never answered the roll (the board's ``Call`` first absentees
after #8349: ``tests/arrays/categorical/test_analytics.py:23:5``'s
``@pytest.mark.parametrize(...)``, ``_testing/_warnings.py:26:1``'s
``@contextmanager``).  The statement evaluates each through the one
decorator step (``_decorator_step``) before its defaults
(``_definition_defaults_sugar``), so each answers by construction.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def _report(source: str):
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(source)
    f.close()
    reporter = CollectingReporter()
    return discharge(
        SourceFile(
            path_source(f.name),
            reporter=reporter,
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )


def test_a_method_decorator_answers_by_construction():
    report = _report(
        "import pytest\n"
        "\n"
        "\n"
        "class TestBox:\n"
        '    @pytest.mark.parametrize("n", [1, 2])\n'
        "    def test_n(self, n):\n"
        "        assert n\n"
    )
    assert not [e for e in report.minority if e.start_line == 5]


def test_a_contextmanager_decorator_answers_by_construction():
    report = _report(
        "from contextlib import contextmanager\n"
        "\n"
        "\n"
        "@contextmanager\n"
        "def opened():\n"
        "    yield 1\n"
    )
    assert not [e for e in report.minority if e.start_line == 4]
