"""An ``except (A, B):`` tuple display answers the roll with its arm (#7757).

The ``try`` consumes a handler's tuple type member by member: each member is
built as one matcher of the arm (``Try._authenticated_handler_specs``), and
the display is never built as a whole, so it never answered (the board's
first absentees ``core/algorithms.py:1504:15``
``except (TypeError, decimal.InvalidOperation):``,
``core/indexes/datetimes.py:1594:15``).  That consumption is its discharge,
as a loop's iterable display is (``For._iterable_evaluated``).
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def _absent_tuples(source: str):
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp")
    f.write(source)
    f.close()
    report = discharge(
        SourceFile(
            path_source(f.name),
            reporter=CollectingReporter(),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )
    return [e for e in report.minority if e.kind == "Tuple"]


def test_a_tuple_handler_type_answers():
    assert not _absent_tuples(
        "def f(g):\n"
        "    try:\n"
        "        return g()\n"
        "    except (KeyError, TypeError) as err:\n"
        "        raise ValueError('bad') from err\n"
    )
