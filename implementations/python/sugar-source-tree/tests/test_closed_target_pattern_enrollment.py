"""Red teeth for #7348: closed producer-owned enrollment, both arms.

The defect: two relations each had a LOUD reader and a DEFAULTING reader over
the same data.  ``target_patterns_for`` mapped three different facts -- table
not built, lawfully not enrolled, and an enrolled row stranded by a rewrite --
onto the same empty tuple, so whether a stale lookup screamed or shrugged
depended on which function the caller happened to call.

Every test in this file is a tooth.  Each one is written to FAIL at
``d0ff65fe537cb4a79374a2a1d90c54a13102462f`` (the reader-deletion pin) and to
pass only once the producer publishes a closed ``Enrolled | NotEnrolled``
outcome and the defaulting readers are gone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_source_tree import nodes
from sugar_source_tree.reporter import NULL_REPORTER
from sugar_source_tree.tree import SourceFile


ENROLLED_SOURCE = """\
def fixture(value):
    root, leaf = split(value)
    return root[leaf]
"""

STORE_ONLY_SOURCE = """\
class Holder:
    def install(self, left, right):
        self.left, self.right = left, right
"""

STORE_LOOP_SOURCE = """\
class Holder:
    def drain(self, items):
        for self.head, self.tail in items:
            pass
"""

LEXICAL_SOURCE = """\
def helper(value):
    return value


def caller(value):
    return helper(value)
"""


def _open(tmp_path: Path, name: str, text: str) -> SourceFile:
    path = tmp_path / name
    path.write_text(text)
    from sugar_lift_python_source.source_oracle import workspace_path_source

    identity = workspace_path_source(str(path), root=str(tmp_path))
    return SourceFile(identity, reporter=NULL_REPORTER)


def _enrolled(tmp_path: Path, tag: str) -> SourceFile:
    """One enrolled-Assign fixture per test.

    SourceUnits are memoized by source CONTENT across opens, so two tests that
    write byte-identical fixtures share one unit -- and a test that strands a
    row would corrupt its neighbour.  The tag keeps each fixture distinct.
    """
    return _open(
        tmp_path,
        f"enrolled_{tag}.py",
        ENROLLED_SOURCE.replace("fixture", f"fixture_{tag}"),
    )


def _sole_assign(source_file: SourceFile):
    return next(node for node in source_file.nodes() if node.kind == "Assign")


def _strand(unit, consumer) -> None:
    """Bypass the mechanism: drop the enrolled row, keep enrollment true.

    This is the mutation the whole issue is about.  It reproduces exactly what
    a rewrite without retention does to the relation, without needing a
    rewrite path that happens to be repaired.
    """
    seated = consumer.require_target_patterns()
    assert seated, "fixture must really own a producer row before stranding"
    unit._target_patterns_by_consumer.pop(consumer.ref)
    return seated


# --------------------------------------------------------------------------
# TOOTH 1 -- the producer publishes a closed applicability outcome at all.
# --------------------------------------------------------------------------


def test_producer_publishes_a_closed_enrollment_outcome(tmp_path: Path) -> None:
    enrolled = _sole_assign(_enrolled(tmp_path, "t1"))
    not_enrolled = _sole_assign(_open(tmp_path, "store.py", STORE_ONLY_SOURCE))

    yes = enrolled.target_pattern_enrollment
    no = not_enrolled.target_pattern_enrollment

    assert isinstance(yes, nodes.TargetPatternEnrolledV1)
    assert isinstance(no, nodes.TargetPatternNotEnrolledV1)
    # Two variants, and they are not interchangeable values.
    assert type(yes) is not type(no)
    assert no.reason == "consumer-shape-not-enrolled"
    assert yes.covers(enrolled.targets[0])


def test_both_declared_non_enrollment_reasons_are_reachable(tmp_path: Path) -> None:
    """Neither named reason is decorative: each has a real source shape."""
    shape = _sole_assign(_open(tmp_path, "store.py", STORE_ONLY_SOURCE))
    loop_file = _open(tmp_path, "store_loop.py", STORE_LOOP_SOURCE)
    loop = next(node for node in loop_file.nodes() if node.kind == "For")

    assert shape.target_pattern_enrollment.reason == "consumer-shape-not-enrolled"
    assert loop.target_pattern_enrollment.reason == "no-binding-leaf-target"


def test_enrollment_outcome_is_closed_and_producer_minted() -> None:
    """The wrong state is unrepresentable, not guarded."""
    with pytest.raises(nodes.TargetPatternConstructionGapV1) as unminted:
        nodes.TargetPatternNotEnrolledV1(
            consumer_occurrence=None, reason="consumer-shape-not-enrolled"
        )
    assert unminted.value.reason == "target-pattern-enrollment-not-producer-minted"

    with pytest.raises(nodes.TargetPatternConstructionGapV1) as third_variant:

        class SmuggledVariant(nodes.TargetPatternEnrollmentV1):
            pass

    assert third_variant.value.reason == (
        "target-pattern-enrollment-variant-not-closed"
    )

    with pytest.raises(nodes.TargetPatternConstructionGapV1) as bad_reason:
        nodes.TargetPatternNotEnrolledV1(
            consumer_occurrence=None,
            reason="made-up",
            _authority=nodes._TARGET_PATTERN_ENROLLMENT_AUTHORITY,
        )
    assert bad_reason.value.reason == (
        "target-pattern-non-enrollment-reason-not-declared"
    )


def test_the_defaulting_target_reader_is_deleted() -> None:
    assert not hasattr(nodes.SourceUnit, "target_patterns_for")
    assert not hasattr(nodes.Node, "target_patterns")
    # The loud readers stay.
    assert hasattr(nodes.SourceUnit, "require_target_pattern")
    assert hasattr(nodes.SourceUnit, "retain_target_patterns")


# --------------------------------------------------------------------------
# TOOTH 2 -- a stranded enrolled row REFUSES; it does not masquerade as
# "this shape was never enrolled".  This is the law, verbatim.
# --------------------------------------------------------------------------


def test_stranded_enrolled_assign_refuses_instead_of_shrugging(
    tmp_path: Path,
) -> None:
    source_file = _enrolled(tmp_path, "t2")
    assignment = _sole_assign(source_file)
    unit = source_file.unit

    # Pre-condition: the row is really there and really read.
    (pattern,) = assignment.require_target_patterns()
    assert pattern.consumer_occurrence is assignment

    _strand(unit, assignment)

    # The applicability answer is UNCHANGED by a lost row.  This is the whole
    # point: enrollment is not read out of the relation.
    assert isinstance(
        assignment.target_pattern_enrollment, nodes.TargetPatternEnrolledV1
    )

    # And the lookup now screams instead of returning a smaller product.
    with pytest.raises(nodes.TargetPatternConstructionGapV1) as stranded:
        assignment.require_target_patterns()
    assert stranded.value.reason == "foreign-target-occurrence"


def test_stranded_enrolled_assign_does_not_fall_through_to_store_construction(
    tmp_path: Path,
) -> None:
    """Caller #5 (``Assign._destructured_binding``) must stop tolerating.

    Before the repair this returned ``None`` -- indistinguishable from a
    lawful mixed/store unpack -- and construction silently continued with a
    weaker answer.
    """
    source_file = _enrolled(tmp_path, "t3")
    assignment = _sole_assign(source_file)
    _strand(source_file.unit, assignment)

    with pytest.raises(nodes.TargetPatternConstructionGapV1) as refused:
        assignment.substitution_binding({})
    assert refused.value.reason == "foreign-target-occurrence"


def test_lawful_store_unpack_still_falls_through_silently(tmp_path: Path) -> None:
    """The other arm of the discriminator: authentic non-enrollment is quiet.

    Run this together with the test above.  If only one of the two passes the
    mechanism is not discriminating, it is just uniformly loud or uniformly
    tolerant.
    """
    source_file = _open(tmp_path, "store.py", STORE_ONLY_SOURCE)
    assignment = _sole_assign(source_file)
    assert isinstance(
        assignment.target_pattern_enrollment, nodes.TargetPatternNotEnrolledV1
    )
    binding = assignment.substitution_binding({})
    assert binding is None or binding == {}


def test_stranded_and_not_enrolled_have_different_representations(
    tmp_path: Path,
) -> None:
    """Absence and lookup-failure never share a representation."""
    enrolled_file = _enrolled(tmp_path, "t4")
    assignment = _sole_assign(enrolled_file)
    _strand(enrolled_file.unit, assignment)

    store_file = _open(tmp_path, "store.py", STORE_ONLY_SOURCE)
    store_assignment = _sole_assign(store_file)

    # Lawful absence is a VALUE.
    absence = store_assignment.target_pattern_enrollment
    assert isinstance(absence, nodes.TargetPatternNotEnrolledV1)

    # Lookup failure is a REFUSAL.  There is no value it could be confused
    # with, because no reader returns a defaulted product any more.
    with pytest.raises(nodes.TargetPatternConstructionGapV1):
        assignment.require_target_patterns()


def test_missing_relation_table_is_its_own_refusal(tmp_path: Path) -> None:
    """The third collapsed fact gets its own name."""
    source_file = _enrolled(tmp_path, "t5")
    assignment = _sole_assign(source_file)
    object.__setattr__(source_file.unit, "_target_patterns_by_consumer", None)

    with pytest.raises(nodes.TargetPatternConstructionGapV1) as unbuilt:
        assignment.require_target_patterns()
    assert unbuilt.value.reason == "target-pattern-table-not-built"


# --------------------------------------------------------------------------
# TOOTH 3 -- ONE authority.  The walk and the published predicate cannot
# disagree, because they are the same function.
# --------------------------------------------------------------------------


def test_producer_walk_and_published_enrollment_are_one_answer(
    tmp_path: Path,
) -> None:
    source_file = _open(
        tmp_path,
        "mixed.py",
        "def fixture(value, items, holder):\n"
        "    root, leaf = split(value)\n"
        "    holder.a, holder.b = value\n"
        "    plain = value\n"
        "    for a, (b, *c) in items:\n"
        "        pass\n"
        "    listed = [a for a, (b, *c) in items]\n"
        "    return root, leaf, plain, listed\n",
    )
    unit = source_file.unit
    seated = set(unit._target_patterns_by_consumer)

    for node in source_file.nodes():
        enrollment = unit.target_pattern_enrollment(node)
        published = isinstance(enrollment, nodes.TargetPatternEnrolledV1)
        # Every enrolled shape has a seated row and vice versa: no shape is
        # enrolled-but-unseated at construction time, and no row exists for a
        # shape the published decision calls not-enrolled.
        assert published == (node.ref in seated), (
            f"{node.kind} disagrees: published={published} "
            f"seated={node.ref in seated}"
        )
        if published:
            assert len(unit.require_target_patterns(node)) == len(
                enrollment.enrolled_targets
            )


# --------------------------------------------------------------------------
# TOOTH 4 -- the LEXICAL arm.  Same law, same defect, blocked on #7346.
# --------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "#7348 lexical arm is prerequisite-blocked on #7346. The lexical "
        "enrollment decision is not a function of the call node -- it needs "
        "the backend's scope/binding classification -- so publishing it "
        "requires a keyed negative table, and a shell/ref-keyed one would "
        "preserve the same defect under a second carrier. Inventing the key "
        "here would be a second answer. This tooth XPASSes loudly the moment "
        "the closed lexical outcome lands."
    ),
)
def test_stranded_enrolled_lexical_call_refuses_instead_of_shrugging(
    tmp_path: Path,
) -> None:
    source_file = _open(tmp_path, "lexical.py", LEXICAL_SOURCE)
    call = next(node for node in source_file.nodes() if node.kind == "Call")
    unit = source_file.unit

    rows = unit.lexical_call_rows_for(call)
    assert rows, "fixture must hold an enrolled lexical call"

    # Same mutation as the target arm: strand the enrolled row.
    constructed = unit.constructed_module
    object.__setattr__(constructed, "lexical_call_rows", ())
    unit._retained_lexical_call_rows.clear()

    # The producer must still say "this occurrence IS enrolled" and the read
    # must refuse. Today the read simply returns () and every consumer treats
    # it as an ordinary non-lexical call.
    enrollment = unit.lexical_call_enrollment(call)
    assert enrollment.__class__.__name__.endswith("EnrolledV1")
    with pytest.raises(nodes.BackendDefect):
        unit.require_lexical_call_rows(call)


def test_the_defaulting_lexical_reader_is_still_present_and_why() -> None:
    """Honest instrument: records exactly what is NOT yet repaired.

    ``lexical_call_rows_for`` still exists and still returns ``()`` for both
    lawful non-enrollment and a stranded row.  Deleting it before the producer
    publishes a closed outcome would force its five callers to re-derive the
    backend's scope walk -- five second answers instead of one side door.
    """
    assert hasattr(nodes.SourceUnit, "lexical_call_rows_for"), (
        "if this reader was deleted, the closed lexical outcome from #7348 "
        "step 3 must have landed -- delete this test with it"
    )
    assert not hasattr(nodes.SourceUnit, "lexical_call_enrollment")
