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

from sugar_source_tree import nodes, occurrence
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
def caller(value):
    def helper(item):
        return item

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
    unit._target_patterns_by_consumer.pop(
        occurrence.SourceOccurrenceIdentityV1.of(consumer)
    )
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
    # Per-consumer retention is gone: the relation is keyed by source
    # occurrence, so a rewrite joins its row without anyone remembering to
    # re-seat it.  A retention door would be a second way to seat a row.
    assert not hasattr(nodes.SourceUnit, "retain_target_patterns")


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
        # The relation is keyed by SOURCE OCCURRENCE, not by the node shell.
        occurrence_key = occurrence.SourceOccurrenceIdentityV1.of(node)
        assert published == (occurrence_key in seated), (
            f"{node.kind} disagrees: published={published} "
            f"seated={occurrence_key in seated}"
        )
        if published:
            assert len(unit.require_target_patterns(node)) == len(
                enrollment.enrolled_targets
            )


# --------------------------------------------------------------------------
# TOOTH 4 -- the LEXICAL arm.  Same law, same defect, blocked on #7346.
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# TOOTH 4 -- the LEXICAL arm.  Same law, same defect; unblocked by #7346.
#
# FIXTURE ISOLATION (#7364): SourceUnits are memoized by (source_cid,
# workspace-relative filename).  Byte-identical fixture text SHARES ONE UNIT
# across tests no matter how distinct the tmp_path is, and two of these teeth
# deliberately CORRUPT the unit they hold.  Every source below is therefore
# unique text under a unique filename.
# --------------------------------------------------------------------------

LEXICAL_NONNAME_SOURCE = """\
def dispatcher(bag):
    marker_nonname = 0
    return bag.handle(marker_nonname)
"""

LEXICAL_MODULE_SCOPE_SOURCE = """\
def target_module_scope(item):
    return item


marker_module_scope = target_module_scope(1)
"""

LEXICAL_NO_BINDING_SOURCE = """\
def outer_no_binding(value):
    marker_no_binding = 1
    return external_no_binding(value, marker_no_binding)
"""

LEXICAL_PARAMETER_BINDING_SOURCE = """\
def outer_parameter_binding(handler):
    marker_parameter_binding = 2
    return handler(marker_parameter_binding)
"""

LEXICAL_DOMAIN_SOURCE = """\
def caller_domain(marker_domain):
    def helper_domain(item):
        return item

    return helper_domain(marker_domain)
"""

LEXICAL_MISS_SOURCE = """\
def caller_miss(value):
    def helper_miss(item):
        return item

    return helper_miss(value)
"""


def _lexical_call(source_file, spelling: str):
    return next(
        node
        for node in source_file.nodes()
        if node.kind == "Call" and getattr(node.func, "id", None) == spelling
    )


def test_stranded_enrolled_lexical_call_refuses_instead_of_shrugging(
    tmp_path: Path,
) -> None:
    """The tooth #7348 was blocked on. It bites the STRAND, not mere failure.

    The producer must still say "this occurrence IS enrolled" after the
    relation is emptied, and the strict read must REFUSE.  Before the closed
    outcome landed, the read simply returned ``()`` and every consumer treated
    a stranded enrolled call as an ordinary non-lexical one.

    Note what is asserted: the enrolled verdict SURVIVES the strand.  A tooth
    that only asserted "something raised" would be satisfied by the enrollment
    lookup itself failing, which is a different fact.
    """
    source_file = _open(tmp_path, "lexical.py", LEXICAL_SOURCE)
    call = next(node for node in source_file.nodes() if node.kind == "Call")
    unit = source_file.unit

    rows = unit.require_lexical_call_rows(call)
    assert rows, "fixture must hold an enrolled lexical call"

    # Same mutation as the target arm: strand the enrolled row.
    constructed = unit.constructed_module
    object.__setattr__(constructed, "lexical_call_rows", ())
    unit._retained_lexical_call_rows.clear()

    enrollment = unit.lexical_call_enrollment(call)
    assert isinstance(enrollment, nodes.LexicalCallEnrolledV1)
    with pytest.raises(nodes.BackendDefect) as stranded:
        unit.require_lexical_call_rows(call)
    assert "0 lexical rows for one enrolled call occurrence" in str(stranded.value)


def test_lookup_miss_refuses_and_never_reports_not_enrolled(tmp_path: Path) -> None:
    """Absence and lookup-failure do not share a representation.

    The producer publishes a decision for EVERY call occurrence it walked, so
    finding none is a failed join.  This is the exact masquerade #7348
    forbids: it must not come back as ``NotEnrolled``.
    """
    source_file = _open(tmp_path, "lexical_miss.py", LEXICAL_MISS_SOURCE)
    call = _lexical_call(source_file, "helper_miss")
    unit = source_file.unit

    assert isinstance(
        unit.lexical_call_enrollment(call), nodes.LexicalCallEnrolledV1
    )

    object.__setattr__(unit.constructed_module, "lexical_call_enrollments", ())

    with pytest.raises(nodes.BackendDefect) as missed:
        unit.lexical_call_enrollment(call)
    assert "0 published enrollment decisions" in str(missed.value)
    assert "SourceUnit.lexical_call_enrollment" in str(missed.value)


def test_every_declared_non_enrollment_reason_is_produced_by_the_walk(
    tmp_path: Path,
) -> None:
    """BOTH ARMS, per reason: each declared reason has a live producer path.

    A closed reason set nobody mints is decoration.  Each case below is a
    ``continue`` the backend walk already executed and used to discard.
    """
    enrolled = _open(tmp_path, "lex_enrolled.py", LEXICAL_MISS_SOURCE)
    assert isinstance(
        enrolled.unit.lexical_call_enrollment(
            _lexical_call(enrolled, "helper_miss")
        ),
        nodes.LexicalCallEnrolledV1,
    )

    cases = (
        ("lex_nonname.py", LEXICAL_NONNAME_SOURCE, None, "non-name-callee"),
        (
            "lex_module.py",
            LEXICAL_MODULE_SCOPE_SOURCE,
            "target_module_scope",
            "module-scope-call",
        ),
        (
            "lex_nobinding.py",
            LEXICAL_NO_BINDING_SOURCE,
            "external_no_binding",
            "no-lexical-binding-in-scope",
        ),
        (
            "lex_parameter.py",
            LEXICAL_PARAMETER_BINDING_SOURCE,
            "handler",
            "binding-not-a-function-definition",
        ),
    )
    for name, text, spelling, reason in cases:
        source_file = _open(tmp_path, name, text)
        call = (
            _lexical_call(source_file, spelling)
            if spelling is not None
            else next(
                node for node in source_file.nodes() if node.kind == "Call"
            )
        )
        outcome = source_file.unit.lexical_call_enrollment(call)
        assert isinstance(outcome, nodes.LexicalCallNotEnrolledV1), (
            f"{name} expected not-enrolled, got {outcome!r}"
        )
        assert outcome.reason == reason, f"{name}: {outcome.reason!r} != {reason!r}"

    assert nodes._LEXICAL_CALL_NON_ENROLLMENT_REASONS == frozenset(
        {reason for *_, reason in cases}
        | {"no-typed-module", "synthesized-call-occurrence"}
    ), "a declared reason with no producer path, or a path with no reason"


def test_synthesized_call_is_out_of_domain_but_a_source_miss_still_refuses(
    tmp_path: Path,
) -> None:
    """BOTH ARMS of the domain discriminator, on one unit.

    The desugarer mints fresh Call shells over a borrowed span; the one
    structural walk never saw them, so they are outside the relation's domain
    rather than a failed join.  That arm is admitted ONLY for a shadow-minted
    node -- a source-backed occurrence with no published decision is still a
    refusal.  A tooth that showed only the first arm would certify a
    masquerade.
    """
    source_file = _open(tmp_path, "lex_domain.py", LEXICAL_DOMAIN_SOURCE)
    unit = source_file.unit
    real_call = _lexical_call(source_file, "helper_domain")
    anchor = next(
        node
        for node in source_file.nodes()
        if node.kind == "Name" and node.id == "marker_domain"
    )

    synthesized = anchor._make_call(anchor)
    assert synthesized.kind == "Call"
    outcome = unit.lexical_call_enrollment(synthesized)
    assert isinstance(outcome, nodes.LexicalCallNotEnrolledV1)
    assert outcome.reason == "synthesized-call-occurrence"

    # Arm two, same table state: the SOURCE call is still decided, and once
    # its decision is removed it refuses instead of taking the domain arm.
    assert isinstance(
        unit.lexical_call_enrollment(real_call), nodes.LexicalCallEnrolledV1
    )
    object.__setattr__(unit.constructed_module, "lexical_call_enrollments", ())
    with pytest.raises(nodes.BackendDefect) as missed:
        unit.lexical_call_enrollment(real_call)
    assert "0 published enrollment decisions" in str(missed.value)


def test_the_lexical_outcome_is_closed_and_producer_minted() -> None:
    """The sealed base refuses a third variant, a foreign mint, and mutation."""
    with pytest.raises(nodes.BackendDefect) as third:

        class _ThirdVariant(nodes.LexicalCallEnrollmentV1):
            pass

    assert "third lexical-call enrollment variant" in str(third.value)

    with pytest.raises(nodes.BackendDefect) as foreign:
        nodes.LexicalCallEnrolledV1(call_occurrence=object())
    assert "minted outside the producer" in str(foreign.value)

    with pytest.raises(nodes.BackendDefect) as undeclared:
        nodes.mint_lexical_call_enrollment(object(), "invented-reason")
    assert "undeclared non-enrollment reason" in str(undeclared.value)

    outcome = nodes.mint_lexical_call_enrollment(object(), None)
    with pytest.raises(nodes.BackendDefect):
        outcome.call_occurrence = object()


def test_the_defaulting_lexical_reader_is_gone() -> None:
    """#7348 step 5: the ambiguous reader is deleted, the loud one stays."""
    assert not hasattr(nodes.SourceUnit, "lexical_call_rows_for")
    assert hasattr(nodes.SourceUnit, "retain_lexical_call_row")
    assert hasattr(nodes.SourceUnit, "require_lexical_call_rows")
