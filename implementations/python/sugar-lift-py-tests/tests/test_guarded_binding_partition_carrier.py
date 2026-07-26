"""Authenticated partition testimony from nested guarded binding reads."""

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.outcome.exit_set import ExitSetFactoringGap
from sugar_lift_py_tests.sugar.binding_projection import GuardedProjection
from sugar_lift_py_tests.sugar.binding_projection import UnboundProjection
from sugar_lift_py_tests.sugar.delete_name_sugar import delete_binding
from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import read_binding
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_source_tree.binding_state import BranchResultSlot


@dataclass(frozen=True)
class _Value(Sugar):
    text: str

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return Complete(StringValue(self.text))


def _slot(name: str) -> BranchResultSlot:
    return BranchResultSlot(f"branch-result:blake3-512:{name}")


@dataclass(frozen=True)
class _Site:
    filename: str = "guarded-binding-partition.py"
    line: int = 1
    col: int = 0


def _read(state):
    return read_binding(
        state,
        read_name="value",
        read_site=_Site(),
        ctx=None,
    )


def test_nested_projection_keeps_ancestor_face_when_equal_leaves_merge():
    """Truthful twin: the outer producer still excludes the distinct sibling."""
    outer = _slot("outer")
    inner = _slot("inner")
    state = GuardedProjection(
        outer,
        GuardedProjection(inner, _Value("same"), _Value("same")),
        _Value("different"),
    )

    exits = _read(state)
    same = next(exit_ for exit_ in exits.exits if exit_.value == StringValue("same"))
    different = next(
        exit_ for exit_ in exits.exits if exit_.value == StringValue("different")
    )

    assert len(exits.exits) == 2
    assert any(
        left.partition == right.partition and left.side != right.side
        for left in same.faces
        for right in different.faces
    )
    exits.factor_completed()


def test_nested_projection_does_not_keep_a_face_the_merged_leaves_disagree_on():
    """Lying twin: a merge spanning both outer sides cannot claim either side."""
    outer = _slot("outer")
    inner = _slot("inner")
    state = GuardedProjection(
        outer,
        GuardedProjection(inner, _Value("same"), _Value("different")),
        _Value("same"),
    )

    exits = _read(state)
    same = next(exit_ for exit_ in exits.exits if exit_.value == StringValue("same"))

    assert not any(face.partition[-1] == outer.slot_id for face in same.faces)


def test_unrelated_projection_arms_still_refuse_without_shared_testimony():
    """Lying twin: two independently owned splits do not buy exclusivity."""
    left = _read(GuardedProjection(_slot("left"), _Value("a"), _Value("b")))
    right = _read(GuardedProjection(_slot("right"), _Value("c"), _Value("d")))

    left_arm = left.exits[0]
    right_arm = right.exits[0]

    with pytest.raises(ExitSetFactoringGap):
        type(left)((left_arm, right_arm)).factor_completed()


def test_delete_stamps_the_same_authenticated_guarded_projection_faces():
    """The other verb over the closed projection union preserves the split."""
    state = GuardedProjection(
        _slot("delete"),
        _Value("bound"),
        UnboundProjection("value", "deleted earlier"),
    )

    exits = delete_binding(
        state,
        name="value",
        site=_Site(),
        ctx=None,
    )

    assert len(exits.exits) == 2
    left, right = exits.exits
    assert any(
        a.partition == b.partition and a.side != b.side
        for a in left.faces
        for b in right.faces
    )
