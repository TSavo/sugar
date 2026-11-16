"""``if o``, ``len(o)`` and ``k in o`` on a source-class instance are the one
undecided member, with the halt face kept (#7757 S4).

An ``ObjectValue`` is made only by ``fresh_receiver``, in a class contract's
own frame.  Its class order picks the ``__bool__`` / ``__len__`` /
``__contains__`` Python runs, and nothing dispatches them: prove's walk does
not carry those protocols.  So each read is the two faces a formal's read
already has -- it completes under its ``completes`` atom and halts
undetermined under the complement, and both arms owe the one ``undecided``
member at the site.  Before, each was a construction panic (``FloorValue``'s
defaults).
"""

from __future__ import annotations

from pathlib import Path

from frame_fresh import FRAME_FRESH

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import ObjectValue, TermValue
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.outcome import Completed
from sugar_source_tree.nodes import ClassDef

_SOURCE = (
    "class Box:\n"
    "    def __len__(self):\n"
    "        return -1\n"
    "\n"
    "\n"
    "def f(o):\n"
    "    return o\n"
)


def _receiver_and_site(tmp_path: Path):
    """A receiver ``Box``'s class call made in the reading frame, and a
    source fragment to read it at."""
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    path = tmp_path / "instance_protocols.py"
    path.write_text(_SOURCE)
    tree = open_source_file_for_construction(path, root=tmp_path)
    statement = next(node for node in tree.root.body if isinstance(node, ClassDef))
    span = statement.binding_target.line_col_span()
    value = ClassDefinitionValue(
        class_name=statement.name,
        class_definition_cid=statement.fragment.seal().cid,
        methods=(),
        initializer=None,
        binding_target_occurrence=SourceFragmentCoordinateV1(
            statement.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        ),
        class_definition=statement,
    )
    receiver = value.fresh_receiver("receiver-cid", allocation=FRAME_FRESH)
    function = next(tree.functions())
    return receiver, function.body[0].fragment


def _assert_owed_two_faces(outcome):
    assert any(isinstance(arm, Completed) for arm in outcome.exits), outcome
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect), halt
    assert len(outcome.owed_items()) == 1, outcome.owed_items()
    for arm in outcome.exits:
        assert arm.owed, arm


def _completed_guard(outcome) -> str:
    (completed,) = (arm for arm in outcome.exits if isinstance(arm, Completed))
    return repr(completed.guard)


def test_instance_truth_is_the_one_truth_rule_s_two_faces(tmp_path):
    receiver, site = _receiver_and_site(tmp_path)
    assert isinstance(receiver, ObjectValue)

    outcome = receiver.truth(site)

    _assert_owed_two_faces(outcome)
    (halt,) = outcome.halts()
    assert halt.effect.producer_node_owner == "ObjectValue.truth"
    assert "python:truth.completes" in _completed_guard(outcome)


def test_instance_length_is_len_s_one_unanswered_call(tmp_path):
    # ``Box.__len__`` returns -1: Python raises ValueError.  Nothing here
    # dispatches it, so the halt face stays (never a completed length).
    receiver, site = _receiver_and_site(tmp_path)

    outcome = receiver.length(site)

    _assert_owed_two_faces(outcome)
    (halt,) = outcome.halts()
    assert halt.effect.producer_node_owner == "UnknownCallee:len"
    assert "python:unknown_callee_call.completes" in _completed_guard(outcome)


def test_instance_membership_is_the_undecided_membership(tmp_path):
    receiver, site = _receiver_and_site(tmp_path)

    outcome = receiver.contains(TermValue(1), site)

    _assert_owed_two_faces(outcome)
    assert "python:compare.completes" in _completed_guard(outcome)
