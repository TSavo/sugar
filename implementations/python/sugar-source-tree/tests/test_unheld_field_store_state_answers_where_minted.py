"""A field store's post-state answers the roll where it is minted (#7757).

``<receiver>.attr = v`` is the one field store (``_receiver_field_store``):
it builds the receiver and the value, and every name holding the object is
rebound to its post-state (``ReceiverFieldStoreState``), which a name's write
or a later read builds.  Where no name holds the object (``a.b.x = v``,
``pd.options.mode.string_storage = "foo"``), nothing reads the post-state, so
nothing constructed it (the board's first absentees
``tests/arithmetic/test_array_ops.py:39:4`` ``right.flags.writeable = False``,
``tests/arrays/string_/test_string_arrow.py:40:8``).  It answers where it is
minted.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def _absent_states(source: str):
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
    return [e for e in report.minority if e.kind == "ReceiverFieldStoreState"]


def test_a_store_through_an_attribute_chain_answers_its_post_state():
    assert not _absent_states(
        "def f(right):\n"
        "    right.flags.writeable = False\n"
        "    return right\n"
    )


def test_a_store_on_a_module_attribute_answers_its_post_state():
    assert not _absent_states(
        "import types\n"
        "\n"
        "def f():\n"
        "    types.SimpleNamespace().x = 1\n"
    )
