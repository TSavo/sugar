"""Authenticated partition testimony from nested guarded binding reads."""

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.outcome.exit_set import (
    ExitSetFactoringGap,
    _faces_exclusive,
)
from sugar_lift_py_tests.sugar.binding_projection import GuardedProjection
from sugar_lift_py_tests.sugar.binding_projection import UnboundProjection
from sugar_lift_py_tests.sugar.delete_name_sugar import delete_binding
from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import (
    _guarded_projection_faces,
    read_binding,
)
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


def test_a_merge_spanning_both_outer_sides_claims_NEITHER_of_them():
    """Lying twin: a merge spanning both outer sides cannot claim either side.

    THIS ARM WAS VACUOUS AND IS REPAIRED HERE. It asserted

        not any(face.partition[-1] == outer.slot_id for face in same.faces)

    and `face.partition[-1]` is the tuple `("binding.projection", slot_id)`,
    never the bare `slot_id` string. The comparison is False for every face
    that has ever existed, so `not any(...)` was true no matter what the merge
    did — the one control standing over this law could not fail.

    The law it MEANT to state is about what the merged arm may claim, and that
    is what is asserted now: an arm reachable on both sides of the outer split
    must not be provably apart from anything on either side. Stated through
    `_faces_exclusive`, because claiming a side is only observable as an
    exclusion — which is also the only way it could ever hurt anything.

    Carrying both sides is how the arm says "one of these, I am not saying
    which", and it is exactly why it excludes neither.
    """
    outer = _slot("outer")
    inner = _slot("inner")
    state = GuardedProjection(
        outer,
        GuardedProjection(inner, _Value("same"), _Value("different")),
        _Value("same"),
    )

    exits = _read(state)
    same = next(exit_ for exit_ in exits.exits if exit_.value == StringValue("same"))
    outer_true, outer_false = _guarded_projection_faces(
        GuardedProjection(outer, _Value("x"), _Value("y"))
    )

    assert not _faces_exclusive(same.faces, frozenset({outer_true}))
    assert not _faces_exclusive(same.faces, frozenset({outer_false}))
    # ...and the discrimination the vacuous form never had: an arm on ONE side
    # of that same split IS provably apart from the other side.
    different = next(
        exit_ for exit_ in exits.exits if exit_.value == StringValue("different")
    )
    assert _faces_exclusive(different.faces, frozenset({outer_false}))


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


# -- the partition's identity is the branch result, not the read site --------


def test_the_same_slot_read_twice_mints_the_SAME_partition() -> None:
    """Salvaged from #6403, whose mechanism landed elsewhere (#6393) while this
    law went unpinned.

    Two reads of one conditional binding are governed by the SAME branch
    outcome, so they must mint the same partition. If the owner were the read
    SITE, or anything allocation-based, two reads of one binding would mint
    unrelated partitions and arms that genuinely exclude each other would look
    merely unrelated -- `factor_completed` would then decline a split that is
    real, silently and with every test green.

    ``partition`` addresses by content, so this is reproducible rather than
    allocation-based. Asserted across two INDEPENDENTLY constructed slot
    objects carrying the same identity, which is what a second read is.
    """
    from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import (
        _guarded_projection_faces,
    )

    first = _guarded_projection_faces(
        GuardedProjection(_slot("shared"), _Value("t"), _Value("f"))
    )
    second = _guarded_projection_faces(
        GuardedProjection(_slot("shared"), _Value("t"), _Value("f"))
    )

    assert first == second


def test_unrelated_conditional_bindings_do_not_share_a_partition() -> None:
    """The discriminating face: reproducibility must not become collapse.

    A single global partition would satisfy the law above and be worthless --
    every unrelated binding would claim to exclude every other.
    """
    from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import (
        _guarded_projection_faces,
    )

    one = _guarded_projection_faces(
        GuardedProjection(_slot("one"), _Value("t"), _Value("f"))
    )
    other = _guarded_projection_faces(
        GuardedProjection(_slot("other"), _Value("t"), _Value("f"))
    )

    assert one != other
    assert {face.partition for face in one} != {face.partition for face in other}


def test_the_two_arms_are_opposite_sides_of_one_split() -> None:
    """Both faces name one partition and differ only in side."""
    from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import (
        _guarded_projection_faces,
    )

    true_face, false_face = _guarded_projection_faces(
        GuardedProjection(_slot("split"), _Value("t"), _Value("f"))
    )

    assert true_face.partition == false_face.partition
    assert true_face.side != false_face.side
