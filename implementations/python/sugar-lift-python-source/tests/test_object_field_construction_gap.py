"""A field read on an instance with no class term is the undecided read.

It was once a Floor gap (a construction panic) where nothing recorded the
field, and the recorded value where a store did.  On main (#7757 L3, #9092)
the lift neither refuses a member's absence nor reads a recorded field
outright: with no class term to state prove's ``plain_read`` under, both are
the one two-faced read, its halt kept and owed.
"""

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import (
    ObjectField,
    ObjectValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import ExitSet, Halted
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile

from frame_fresh import FRAME_FRESH


def _site(tmp_path, member):
    path = tmp_path / "read_field.py"
    path.write_text(f"def read(receiver):\n    return receiver.{member}\n")
    return next(
        node.fragment
        for node in SourceFile(
            workspace_path_source(str(path), root=str(tmp_path))
        ).nodes()
        if node.kind == "Attribute"
    )


def _the_undecided_read(outcome):
    """The one two-faced read: a halt kept, undetermined (never the lift's
    ``AttributeError``, never a construction panic), the read owed."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    halts = outcome.halts()
    assert halts
    for halt in halts:
        assert not isinstance(halt.effect, RaiseEffect)
        assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert outcome.owed_items()


@pytest.mark.parametrize(
    "class_name, member", [("RenamedResource", "acquired"), ("Unrelated", "payload")]
)
def test_written_and_missing_fields_are_the_dispatched_read(tmp_path, class_name, member):
    # An instance with no class term (no class statement, no workspace root)
    # names nothing prove's plain_read could decide (#9092): a recorded field
    # is never read outright, and a field nothing recorded is never the
    # lift's refusal (L3: the lift never decides a member's absence).  Both
    # are the dispatched read, here the one undecided read.
    site = _site(tmp_path, member)
    receiver = ObjectValue(
        class_name, (ObjectField("marker", TermValue(3)),), allocation=FRAME_FRESH
    )
    written = receiver.with_field_store(member, TermValue(7))
    read = written.attribute(member, site, None)
    assert read != ExitSet.completed(TermValue(7))
    _the_undecided_read(read)

    missing = receiver.attribute(member, site, None)
    assert TermValue(7) not in [
        face.value for face in missing.exits if not isinstance(face, Halted)
    ]
    _the_undecided_read(missing)


def test_deleted_field_is_never_read_back_and_never_a_lift_attribute_error(tmp_path):
    """A read of a field a delete removed is not the lift's ``AttributeError``
    (a ``__getattr__`` may answer it).  The delete is the dispatched
    ``__delattr__`` (#7757 H1c), both faces kept; on every object it may
    leave, the read is the undecided read, owed, its halting face kept, and
    never the deleted value."""
    site = _site(tmp_path, "payload")
    receiver = ObjectValue(
        "Renamed", (ObjectField("payload", TermValue(7)),), allocation=FRAME_FRESH
    )
    deleted = receiver.delattr("payload", site, None)
    assert deleted.halts()
    after = [face.value for face in deleted.exits if not isinstance(face, Halted)]
    assert after
    for value in after:
        outcome = value.attribute("payload", site, None)
        assert outcome.completed_value() != TermValue(7)
        _the_undecided_read(outcome)


def test_unknown_receiver_type_is_the_two_faced_unanswered_read(tmp_path):
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    site = _site(tmp_path, "payload")
    receiver = SymbolicValue(make_var("unknown_receiver"))
    outcome = receiver.attribute("payload", site, None)
    (halt,) = [arm for arm in outcome.exits if isinstance(arm, Halted)]
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.effect.producer_node_owner == "SymbolicValue.attribute"
    assert [item.site is not None for item in owed_calls(outcome)] == [True]
