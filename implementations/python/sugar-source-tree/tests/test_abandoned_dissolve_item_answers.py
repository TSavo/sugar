"""An item a comprehension's dissolve mints over a ground list answers the roll
where it is minted, with its index (#7757).

A comprehension over a name bound to a ground list (``dates = [...]``) reads
each item as ``dates[i]`` (``For._item_of``), with the index minted at the
comprehension's span (``For._int_constant``).  A dict or set comprehension
whose key no ground value hashes (``{Timestamp(d): ... for d in dates}``)
gives up its dissolve after minting them, and nothing built the index: on the
pandas board at ``d54a43717`` (run 43739300912) two files ended in
``Constant registered but never answered the roll call`` at the comprehension
(``tests/groupby/test_timegrouper.py:528``, ``tests/io/test_stata.py:767``).
Each item now answers where it is minted with its index
(``_minted_member_read``), as an unpack's member read does.
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
        "def f(T, D):\n    dates = ['a', 'b']\n"
        "    return {T(d): D([d]) for d in dates}\n",
        "def f():\n    columns = ['tc', 'td']\n    return {c: c for c in columns}\n",
        "def f(T):\n    xs = [1, 2]\n    return {T(x) for x in xs}\n",
    ],
)
def test_no_item_or_index_of_a_dissolve_is_left_unanswered(source):
    report = _report(source)
    assert not [
        e for e in report.minority if e.kind in {"Constant", "Subscript"}
    ], report.minority
