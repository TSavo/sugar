"""Teeth for the closed finite-projection decision (#7347).

The defect: `_finite_map` answered a bare `None` for at least four distinct
facts, `_after_iterable` erased all four into one symbolic fallback, and the
comprehension issued `Complete(ComprehensionValue, finite_elements=None)`. A
comprehension whose finite projection was lost to a STRANDED AUTHENTICATED
LOOKUP was therefore indistinguishable, at the verdict, from a genuinely
unbounded one.

Both arms are pinned here on purpose. Lawful inapplicability MUST still reach
symbolic `Complete`; a failed authenticated lookup MUST refuse. A test that
only shows the refusal proves nothing about whether the lawful arm survived.
"""

from dataclasses import dataclass, replace

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.comprehension_sugar import (
    ComprehensionGeneratorSugar,
    ComprehensionSugar,
    ComprehensionTargetSugar,
)
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.finite_projection import (
    FiniteProjectionNonSuccessV1,
    FiniteProjectionRefusalV1,
    NotProjected,
    Projected,
    require_finite_projection_decision,
)
from sugar_source_tree.nodes import (
    TargetPatternConstructionGapV1,
    TargetPatternEnrolledV1,
)
from producer_minted_enrollment import producer_enrolled, producer_not_enrolled
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class _InertSugar(ConstructedTermSugar):
    """A well-formed iterable sugar, so a constructor raise has ONE cause."""

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(None)

    def to_term(self, *, owner: str):
        del owner
        raise AssertionError("inert sugar is never termed")


def _source_file(source: str):
    return SourceFile(
        (
            source,
            "tests/finite_projection_decision_fixture.py",
            blake3_512_of(source.encode()),
        ),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _symbolic_binding():
    """A real Node to bind a name to, whose value is not ground."""
    source = "def g(seed):\n    return seed\n"
    return next(
        node
        for node in _source_file(source).root.walk()
        if node.kind == "Name" and node.id == "seed"
    )


_REWRITE_SOURCES = {
    # A finite literal iterable, a DESTRUCTURING target, and an element that
    # mentions a free name. Substituting that name rewrites the comprehension
    # (fresh parent ref) while keeping the iterable exactly finite -- the exact
    # shape #7347 executed.
    "py.setcomp": "def build(y):\n    return {(a, b, y) for a, b in [(1, 2), (3, 4)]}\n",
    "py.dictcomp": (
        "def build(y):\n    return {(a, y): b for a, b in [(1, 2), (3, 4)]}\n"
    ),
    "py.generatorexp": (
        "def build(y):\n    return ((a, b, y) for a, b in [(1, 2), (3, 4)])\n"
    ),
}
_KIND_NODE = {
    "py.setcomp": "SetComp",
    "py.dictcomp": "DictComp",
    "py.generatorexp": "GeneratorExp",
}


def _rewritten(kind: str, *, tag: str = ""):
    # #7364: SourceUnits are memoized by (source_cid, filename), so two fixtures
    # with byte-identical text SHARE ONE UNIT -- and a test that drops a row
    # would corrupt its neighbours.  ``tag`` keeps each fixture's text distinct.
    source = _REWRITE_SOURCES[kind]
    if tag:
        source += f"# unique fixture bytes: {tag}\n"
    source_file = _source_file(source)
    node = next(
        candidate
        for candidate in source_file.nodes()
        if candidate.kind == _KIND_NODE[kind]
    )
    rewritten = node.substitute({"y": _symbolic_binding()})
    assert rewritten is not node, "fixture did not rewrite the comprehension"
    assert rewritten.kind == _KIND_NODE[kind], "fixture unrolled to a display"
    return node, rewritten


def _stranded(kind: str, tag: str):
    """A rewritten consumer whose producer row is EXPLICITLY dropped.

    A rewrite alone no longer strands anything: #7346-A keys the relation by
    ``SourceOccurrenceIdentityV1``, and ``shadow.rewrite`` borrows the origin's
    span, so the rewrite joins its own row.  The refusal these teeth pin is a
    property of a FAILED AUTHENTICATED LOOKUP, not of the rewrite that used to
    cause one -- so the row is now removed on purpose, and the teeth below bite
    on exactly the same refusal as before.
    """
    from sugar_source_tree.occurrence import SourceOccurrenceIdentityV1

    node, rewritten = _rewritten(kind, tag=f"stranded-{kind}-{tag}")
    rewritten.unit._target_patterns_by_consumer.pop(
        SourceOccurrenceIdentityV1.of(rewritten)
    )
    return node, rewritten


# --------------------------------------------------------------------------
# The carrier is closed at the TYPE, not at a guard.
# --------------------------------------------------------------------------


def test_the_non_success_reasons_are_exactly_the_four_ruled_causes():
    assert {reason.value for reason in FiniteProjectionNonSuccessV1} == {
        "lawfully-inapplicable",
        "projection-unavailable-in-context",
        "authenticated-lookup-failed",
        "replacement-failed",
    }


def test_the_decision_boundary_rejects_none():
    with pytest.raises(TypeError):
        require_finite_projection_decision(None, owner="tooth")


def test_the_decision_boundary_rejects_a_foreign_value():
    with pytest.raises(TypeError):
        require_finite_projection_decision(Complete(None), owner="tooth")


def test_not_projected_rejects_an_undeclared_reason():
    with pytest.raises(TypeError):
        NotProjected("authenticated-lookup-failed")
    with pytest.raises(TypeError):
        NotProjected(None)


def test_projected_transports_an_outcome_and_never_none():
    with pytest.raises(TypeError):
        Projected(None)
    with pytest.raises(TypeError):
        Projected(object())


def test_enrollment_values_are_producer_minted_and_cannot_be_forged():
    """#7348 owns the type and its authority. This sugar mints nothing."""
    from sugar_source_tree.nodes import TargetPatternNotEnrolledV1

    with pytest.raises(TargetPatternConstructionGapV1):
        TargetPatternNotEnrolledV1(
            consumer_occurrence=None, reason="consumer-shape-not-enrolled"
        )
    assert isinstance(producer_not_enrolled(), TargetPatternNotEnrolledV1)


def _generator(**overrides):
    fields = dict(
        target=ComprehensionTargetSugar(source_name="x"),
        binding_coordinate_cid="cid",
        iterable=_InertSugar(),
        filters=(),
        target_pattern_enrollment=producer_not_enrolled(),
    )
    fields.update(overrides)
    return ComprehensionGeneratorSugar(**fields)


def test_generator_sugar_requires_a_producer_enrollment_answer():
    # The control: every other field is well-formed, so a raise can only be
    # about the enrollment answer.
    assert _generator() is not None

    fields = dict(
        target=ComprehensionTargetSugar(source_name="x"),
        binding_coordinate_cid="cid",
        iterable=_InertSugar(),
        filters=(),
    )
    with pytest.raises(TypeError) as missing:
        ComprehensionGeneratorSugar(**fields)
    assert "target_pattern_enrollment" in str(missing.value)

    with pytest.raises(TypeError) as absent:
        _generator(target_pattern_enrollment=None)
    assert "target_pattern_enrollment" in str(absent.value)

    with pytest.raises(TypeError) as foreign:
        _generator(target_pattern_enrollment="enrolled")
    assert "target_pattern_enrollment" in str(foreign.value)


# --------------------------------------------------------------------------
# The producer publishes enrollment; this reader never reconstructs it.
# --------------------------------------------------------------------------


def test_producer_publishes_enrollment_for_a_destructuring_comprehension():
    node, enrollment = producer_enrolled(_REWRITE_SOURCES["py.setcomp"], "SetComp")

    assert isinstance(enrollment, TargetPatternEnrolledV1)
    # The consumer-level answer covers THIS generator slot -- the assumption
    # `_finite_map` rests on, pinned rather than argued.
    assert enrollment.covers(node.generators[0].target)


def test_a_rewritten_consumer_keeps_both_its_enrollment_and_its_row():
    """#7346-A: a rewrite is no longer a way to lose a row.

    The relation is keyed by source occurrence and ``shadow.rewrite`` borrows
    the origin's span, so the rewritten consumer is the SAME occurrence and
    joins the producer's row -- with no per-consumer retention call.
    """
    origin, rewritten = _rewritten("py.setcomp")

    assert isinstance(
        rewritten.unit.target_pattern_enrollment(rewritten), TargetPatternEnrolledV1
    )
    assert rewritten.unit.require_target_patterns(
        rewritten
    ) == origin.unit.require_target_patterns(origin)


def test_an_enrolled_consumer_whose_row_is_gone_stays_owed_and_refuses():
    """The two facts are still separable: still OWED, no longer FOUND."""
    _, stranded = _stranded("py.setcomp", "owed-but-not-found")

    assert isinstance(
        stranded.unit.target_pattern_enrollment(stranded), TargetPatternEnrolledV1
    )
    with pytest.raises(TargetPatternConstructionGapV1):
        stranded.unit.require_target_patterns(stranded)


# --------------------------------------------------------------------------
# ARM ONE: a failed authenticated lookup refuses and never reaches Complete.
#
# THE JOIN. On the merged tree #7348's `_recurrence_generators` reads the row
# STRICTLY, so a stranded comprehension now refuses at SUGAR CONSTRUCTION,
# before `_finite_map` is ever called. The verdict-level defect is closed
# twice over, and these two teeth say which door bites where.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(_REWRITE_SOURCES))
def test_stranded_target_pattern_never_reaches_a_complete_verdict(kind):
    _, stranded = _stranded(kind, "never-reaches-complete")

    with pytest.raises(
        (TargetPatternConstructionGapV1, FiniteProjectionRefusalV1)
    ) as refused:
        stranded.sugar().desugar(None)

    # On the merged tree the producer-side door is the one that bites.
    assert isinstance(refused.value, TargetPatternConstructionGapV1)
    assert refused.value.reason == "foreign-target-occurrence"


@pytest.mark.parametrize("kind", sorted(_REWRITE_SOURCES))
def test_the_projection_arm_still_refuses_an_enrolled_slot_without_its_pattern(kind):
    """The backstop, exercised directly.

    #7348 closed the producer path that USED to reach here. The decision arm
    stays because the invariant is a property of the projection, not of one
    caller: any future callsite that hands `_finite_map` an enrolled slot with
    no pattern must refuse, not spend a `Complete`.
    """
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    node, enrollment = producer_enrolled(_REWRITE_SOURCES[kind], _KIND_NODE[kind])
    sugar = node.sugar()
    stranded = replace(
        sugar.generators[0],
        target_coordinates=(),
        target_pattern=None,
    )
    assert stranded.target.coordinates is not None
    assert isinstance(stranded.target_pattern_enrollment, TargetPatternEnrolledV1)

    decision = sugar._finite_map(stranded, TupleValue(()), None)

    assert decision == NotProjected(
        FiniteProjectionNonSuccessV1.AUTHENTICATED_LOOKUP_FAILED
    )
    with pytest.raises(FiniteProjectionRefusalV1) as refused:
        sugar._after_iterable(stranded, TupleValue(()), 0, (), None)
    assert (
        refused.value.reason
        is FiniteProjectionNonSuccessV1.AUTHENTICATED_LOOKUP_FAILED
    )
    assert refused.value.construct == kind
    assert refused.value.coordinate
    assert refused.value.shape == "destructure:2"


# --------------------------------------------------------------------------
# ARM TWO: the lawful arms are untouched. Symbolic Complete stays lawful.
# --------------------------------------------------------------------------


def test_a_genuinely_unbounded_comprehension_still_completes_symbolically():
    source = "def build(items):\n    return {a for a in items}\n"
    node = next(
        candidate for candidate in _source_file(source).nodes()
        if candidate.kind == "SetComp"
    )

    outcome = node.sugar().desugar(None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ComprehensionValue)
    assert outcome.value.finite_elements is None


def test_the_listcomp_retention_control_still_projects_finite_elements():
    source = (
        "def build():\n"
        "    return [(left, right) for left, right in [(1, 2), (3, 4)]]\n"
    )
    call_source = source + "build()\n"
    call = tuple(
        node
        for node in _source_file(call_source).nodes()
        if node.kind == "Call" and node.func.kind == "Name" and node.func.id == "build"
    )[-1]

    outcome = call.sugar().desugar(None)

    assert isinstance(outcome, Complete)


def test_a_lawful_reason_is_not_spent_as_a_refusal():
    """`_finite_map` answers a typed non-success, not a bare sentinel."""
    source = "def build(items):\n    return {a for a in items}\n"
    node = next(
        candidate for candidate in _source_file(source).nodes()
        if candidate.kind == "SetComp"
    )
    sugar = node.sugar()
    generator = sugar.generators[0]

    decision = sugar._finite_map(generator, object(), None)

    require_finite_projection_decision(decision, owner="tooth")
    assert decision == NotProjected(
        FiniteProjectionNonSuccessV1.LAWFULLY_INAPPLICABLE
    )


def test_projection_unavailable_in_context_is_its_own_reason():
    """A finite iterable plus a context with no temporal projection."""
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    source = "def build(items):\n    return {a for a in items}\n"
    node = next(
        candidate for candidate in _source_file(source).nodes()
        if candidate.kind == "SetComp"
    )
    sugar = node.sugar()

    decision = sugar._finite_map(sugar.generators[0], TupleValue(()), None)

    assert decision == NotProjected(
        FiniteProjectionNonSuccessV1.PROJECTION_UNAVAILABLE_IN_CONTEXT
    )


def test_replacement_failure_is_its_own_reason_and_never_a_finite_verdict():
    """A context that carries `temporal` but cannot be replaced."""
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    class _UnreplaceableContext:
        temporal = object()

    source = "def build(items):\n    return {a for a in items}\n"
    node = next(
        candidate for candidate in _source_file(source).nodes()
        if candidate.kind == "SetComp"
    )
    sugar = node.sugar()

    decision = sugar._finite_map(
        sugar.generators[0], TupleValue(()), _UnreplaceableContext()
    )

    assert decision == NotProjected(FiniteProjectionNonSuccessV1.REPLACEMENT_FAILED)
    with pytest.raises(FiniteProjectionRefusalV1) as refused:
        sugar._after_iterable(
            sugar.generators[0], TupleValue(()), 0, (), _UnreplaceableContext()
        )
    assert refused.value.reason is FiniteProjectionNonSuccessV1.REPLACEMENT_FAILED


def test_swapped_target_coordinates_still_refuse():
    """A pre-existing refusal, re-run: this change weakens nothing."""
    from sugar_source_tree.nodes import TargetPatternConstructionGapV1

    source = "def build():\n    return [(left, right) for left, right in [(1, 2)]]\n"
    comprehension = next(
        node for node in _source_file(source).nodes() if node.kind == "ListComp"
    ).sugar()
    generator = comprehension.generators[0]

    with pytest.raises(TargetPatternConstructionGapV1):
        replace(
            generator,
            target_coordinates=tuple(reversed(generator.target_coordinates)),
        )
