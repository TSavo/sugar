"""A partition key must discriminate EXECUTIONS, not only source locations.

#6438 pinned half of this law: two reads of one conditional binding must mint
the SAME partition, so arms that genuinely exclude each other are recognized.
That is reproducibility, and it is necessary.

It is not sufficient. A key that is a pure source address ALSO makes two
different executions over that source look like two sides of one split --
and ``_faces_exclusive`` never reads the arms' guards. Its own docstring says
it "only asks whether two arms carry the same origin with a different side", so
distinct guard values are no defence. The face testimony alone decides.

Measured, and the reason this file exists:

    source-only key, two executions  ->  ONE arm.  The two collapse into
        ``GuardedValue(guard=<execution 1's guard>, when_true=v1, when_false=v2)``
        -- which asserts that execution 2's value is what you get when
        execution 1's guard is false. They are unrelated executions. Nothing is
        dropped; execution 2's face is RE-ATTRIBUTED to the negation of a guard
        that has nothing to do with it.

The fix is an execution discriminator ALONGSIDE the source coordinate, not
instead of it:

    source alone     reproducible, but conflates executions
    execution alone  discriminates, but is unreproducible and not
                     content-addressable -- a per-call runtime identity
    both             reproducible AND non-conflating

``GeneratorConstructionV1.instance_coordinate`` is minted by ``cid_of_json``
over allocation + frame + steps, so it is content-addressed rather than
allocation-based and can serve as that discriminator without breaking
addressing.

The loop carrier already states this law and pins it -- ``targetCid`` is the
producer OCCURRENCE, and ``test_two_occurrences_with_identical_faces_are_different_states``
says so directly. This file states it as a property of the KEY rather than of
one carrier, so a new partition producer cannot rediscover the defect.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.ir import atomic
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, partition

FRAGMENT = "if@renamed_module.py:2:4"


def _two_arms(left_key, right_key, left_guard: str, right_guard: str):
    """One arm on each key's opposite side, carrying different values."""
    left_face, _ = partition(left_key)
    _, right_face = partition(right_key)
    return ExitSet(
        (
            Completed(atomic(left_guard, ()), TermValue(1), frozenset({left_face}), ()),
            Completed(
                atomic(right_guard, ()), TermValue(2), frozenset({right_face}), ()
            ),
        )
    )


def _completed(exits: ExitSet) -> int:
    return len([e for e in exits.exits if isinstance(e, Completed)])


# -- the defect a source-only key admits -------------------------------------


def test_a_source_only_key_conflates_two_executions() -> None:
    """THE measurement. Two unrelated executions collapse into one arm.

    This is asserted, not merely described, so that any future "fix" which
    quietly makes source-only keys safe has to come here and say so.
    """
    source_only = ("generator.branch", FRAGMENT)

    factored = _two_arms(source_only, source_only, "execution_1", "execution_2")
    collapsed = factored.factor_completed()

    assert _completed(collapsed) == 1

    value = collapsed.exits[0].value
    # Execution 2's value is now the else-branch of execution 1's guard.
    assert value.when_true == TermValue(1)
    assert value.when_false == TermValue(2)
    assert value.guard == atomic("execution_1", ())


# -- the composite key refuses it, loudly ------------------------------------


def test_a_composite_key_refuses_to_factor_across_executions() -> None:
    """The fix, and it is `panic = gap` rather than a silent separation.

    Two arms from distinct executions are not provably exclusive, so
    `factor_completed` states a named `ExitSetFactoringGap` instead of picking
    one. A silent pass-through would be safe here but dishonest elsewhere: the
    algebra must say it could not prove the split, not quietly decline to use
    it.
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSetFactoringGap

    one = ("generator.branch", "instance-AAA", FRAGMENT)
    other = ("generator.branch", "instance-BBB", FRAGMENT)

    with pytest.raises(ExitSetFactoringGap):
        _two_arms(one, other, "execution_1", "execution_2").factor_completed()


def test_a_composite_key_still_factors_within_one_execution() -> None:
    """The discriminating face: the discriminator must not break real splits.

    A key that never factored anything would pass the test above and be
    worthless. Two faces of ONE execution's branch are a genuine partition and
    must still collapse to a `GuardedValue` chain at the value level, which is
    what keeps sequencing from multiplying.
    """
    one = ("generator.branch", "instance-AAA", FRAGMENT)

    collapsed = _two_arms(one, one, "c", "not_c").factor_completed()

    assert _completed(collapsed) == 1
    assert collapsed.exits[0].value.guard == atomic("c", ())


# -- the law stated on the key itself ----------------------------------------


def test_the_discriminator_changes_the_partition_identity() -> None:
    """Two executions over one source must mint DIFFERENT partitions."""
    one = partition(("generator.branch", "instance-AAA", FRAGMENT))
    other = partition(("generator.branch", "instance-BBB", FRAGMENT))

    assert one != other
    assert {face.partition for face in one} != {face.partition for face in other}


def test_the_source_coordinate_still_gives_reproducibility() -> None:
    """#6438's half of the law survives: same execution, same source, same
    partition -- across two independently constructed keys."""
    key = ("generator.branch", "instance-AAA", FRAGMENT)

    assert partition(key) == partition(
        ("generator.branch", "instance-AAA", "if@renamed_module.py:2:4")
    )


def test_dropping_the_source_coordinate_breaks_reproducibility() -> None:
    """The other discriminating face: an execution-ONLY key is not the fix.

    It would pass every test above and still be wrong -- two branches within
    one execution would share a partition and be declared exclusive.
    """
    first_branch = ("generator.branch", "instance-AAA", "if@m.py:2:4")
    second_branch = ("generator.branch", "instance-AAA", "if@m.py:9:4")

    assert partition(first_branch) != partition(second_branch)
