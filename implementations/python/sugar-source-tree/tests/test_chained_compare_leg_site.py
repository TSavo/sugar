"""A chained comparison's legs are read off its source operands (#7757).

``Compare._comparison_leg_site`` authenticates each leg's operator interval
against the two operands it separates.  After substitution an operand is a
read of a binding whose node may stand at another span, and the leg was
refused with a bare tuple for a message (``core/arrays/_ranges.py:145:8``
``endpoint < 0 < stride``, ``tests/base/test_misc.py:108:15`` ``res_deep ==
res == expected``).  Substitution now carries each leg's interval from the
source operands (``leg_gaps``), and a refusal names what it saw.
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
        "def f(a, b):\n    expected = 0\n    assert a == b == expected\n",
        "def f(endpoint, stride, side):\n"
        "    if (endpoint > 0 and side == 'start') or (\n"
        "        endpoint < 0 < stride and side == 'end'\n"
        "    ):\n"
        "        return 1\n"
        "    return 0\n",
    ],
)
def test_a_substituted_chain_keeps_its_leg_sites(source):
    report = _report(source)
    owners = [getattr(panic, "owner", None) for _node, panic in report.reporter.gaps]
    assert "Compare._comparison_leg_site" not in owners
