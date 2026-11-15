"""A call that seats its callee's frame by name answers the callee's Name
(#7757).

A call of a local generator function, ``async def`` or ``contextmanager``
generator seats the definition's frame through its lexical row
(``Call._construct_sugar``) and is spelled by its callee
(``CallSiteSugar.target_name``): the callee's Name is absorbed, never
constructed.  The call by name below that path discharges the absorbed Name;
this one did not, so the Name stayed on the roll unanswered: five files on
the pandas board at ``d54a43717`` (run 43739300912), ``reader = _read()``
(``io/parsers/python_parser.py:267``), ``list(_dict_round(self, decimals))``
(``core/frame.py:13034``), ``DataFrame(empty_gen(), ...)``,
``json_normalize(generator_data())``, ``tuple_generator(10)``.
"""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def _report(source: str):
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(source)
    f.close()
    return discharge(
        SourceFile(
            path_source(f.name),
            reporter=CollectingReporter(),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )


@pytest.mark.parametrize(
    "source",
    [
        "def f(lines):\n    def _read():\n        yield from lines\n"
        "    reader = _read()\n    return reader\n",
        "def f():\n    def empty_gen():\n        yield from ()\n"
        "    return list(empty_gen())\n",
        "def f(n):\n    async def g():\n        return n\n    return g()\n",
    ],
)
def test_the_seated_callee_name_answers(source):
    report = _report(source)
    assert not [e for e in report.minority if e.kind == "Name"], report.minority
