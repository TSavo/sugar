"""A missing constructed field is a Floor gap, not an unknown receiver type."""

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import (
    ObjectField,
    ObjectValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.gap.info import GapKind, GapLocus
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import ExitSet
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


@pytest.mark.parametrize(
    "class_name, member", [("RenamedResource", "acquired"), ("Unrelated", "payload")]
)
def test_missing_field_panics_but_written_twin_projects(tmp_path, class_name, member):
    site = _site(tmp_path, member)
    receiver = ObjectValue(
        class_name, (ObjectField("marker", TermValue(3)),), allocation=FRAME_FRESH
    )
    written = receiver.with_field_store(member, TermValue(7))
    assert written.attribute(member, site, None) == ExitSet.completed(TermValue(7))

    # The write belongs to its own state, not to the original/other guard face.
    with pytest.raises(ConstructionPanic) as caught:
        receiver.attribute(member, site, None)
    assert not isinstance(caught.value, Exception)
    info = caught.value.info
    assert info.owner == "ObjectValue.attribute"
    assert info.observed == f"ObjectValue.{member}"
    assert info.gap_kind is GapKind.FLOOR
    assert info.gap_locus is GapLocus.CONSTRUCTION
    assert "read_field.py" in info.blame
    assert "source-authenticated" in info.requested


def test_deleted_field_is_never_read_back_and_never_a_lift_attribute_error(tmp_path):
    """A read of a field a delete removed is not the lift's ``AttributeError``
    (a ``__getattr__`` may answer it): with no class statement, whose order
    nothing reads, it is the undecided read, owed, its halting face kept
    (#7757 L3; with a class it is the dispatched read prove's walk
    decides)."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    site = _site(tmp_path, "payload")
    receiver = ObjectValue(
        "Renamed", (ObjectField("payload", TermValue(7)),), allocation=FRAME_FRESH
    )
    deleted = receiver.delattr("payload", site, None)
    deleted_value = deleted.completed_value()
    assert deleted_value is not None
    outcome = deleted_value.attribute("payload", site, None)
    assert outcome.completed_value() != TermValue(7)
    (halt,) = outcome.halts()
    assert not isinstance(halt.effect, RaiseEffect)
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert outcome.owed_items()


def test_unknown_receiver_type_is_the_two_faced_unanswered_read(tmp_path):
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Halted
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    site = _site(tmp_path, "payload")
    receiver = SymbolicValue(make_var("unknown_receiver"))
    outcome = receiver.attribute("payload", site, None)
    (halt,) = [arm for arm in outcome.exits if isinstance(arm, Halted)]
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.effect.producer_node_owner == "SymbolicValue.attribute"
    assert [item.site is not None for item in owed_calls(outcome)] == [True]
