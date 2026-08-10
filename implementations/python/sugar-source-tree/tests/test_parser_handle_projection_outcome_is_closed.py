"""TWO FAULTS, NOT ONE: a failed projection lookup is not a missing category.

``Call._project_constructed_value_for_testimony`` exists to swap a raw parser
``.ref`` for this roll's typed occurrence. When it could not, it returned the
value unprojected -- silently -- and canonicalization then met a raw
``cpython_adapter._Handle`` and refused it as an ``unclassified constructed
value category``.

That sentence names the wrong fault. The category is not missing. ``_Handle``
is deliberately uncategorized parser machinery with no authenticated content,
and broadening the category to admit it would be strictly worse than the gap
(``test_raw_or_reminted_parser_handle_never_becomes_semantic_testimony`` pins
that, and this repair leaves it standing). What actually failed was the
LOOKUP -- and the reader could not tell, because "there was no ref to project"
and "there was a ref and nothing answered for it" shared one representation:
the function returned ``value`` for both.

These teeth pin the split as a CLOSED SET that reconciles:

    RollProjectsNothing       this roll seats no table; it projects nothing
    NothingToProject          no ref was carried; none was ever owed
    ParserHandleProjected     the roll owns the typed occurrence for the ref
    ParserHandleLookupFailed  a ref WAS carried and nothing answered for it

and an outcome nobody wrote an arm for raises by name rather than falling
through as "no change".

RollProjectsNothing is here because the pandas slice REFUTED its absence. A
first version folded it into ParserHandleLookupFailed, and a unit tooth
asserting that only the canonicalizing roll reaches this projection passed
while being false about production: 61 measured files became instrument
failures. That is why the fourth member exists and why its tooth is written
against the production shape rather than against the class hierarchy.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar

from sugar_source_tree.backend import materialize
from sugar_source_tree.binding_state import (
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
)
from sugar_source_tree.nodes import (
    Call,
    FunctionDef,
    NothingToProject,
    PARSER_HANDLE_PROJECTION_OUTCOMES,
    ParserHandleLookupFailed,
    ParserHandleProjected,
    RollProjectsNothing,
)
from sugar_source_tree.panic import (
    BackendDefect,
    ConstructedValueTestimonyNotWritten,
)
from sugar_source_tree.reporter import CollectingReporter


def _roll(tmp_path, *, name: str, helper: str = "helper", caller: str = "caller"):
    """One authenticated roll: its source, its definition, its call, its roll."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / f"{name}.py"
    path.write_text(
        f"def {helper}(value):\n"
        "    return value\n\n"
        f"def {caller}(value):\n"
        f"    return {helper}(value)\n"
    )
    collector = CollectingReporter()
    source = open_source_file_for_construction(
        path,
        root=tmp_path,
        reporter=collector,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )
    reporter = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(source.unit.source_cid)
    )
    root = materialize(source.unit, source.root.ref, reporter)
    definition = next(
        node
        for node in root.walk()
        if isinstance(node, FunctionDef) and node.name == helper
    )
    call = next(
        node
        for node in root.walk()
        if isinstance(node, Call) and node.segment() == f"{helper}(value)"
    )
    return source, definition, call, reporter


# ---------------------------------------------------------------------------
# THE CLOSED SET -- all three outcomes, each on its own real roll
# ---------------------------------------------------------------------------


def test_absence_and_lookup_failure_are_different_members(tmp_path) -> None:
    """The two that used to be one ``return value``.

    Both arms are exercised on the SAME call, so the only controlled variable
    is what is asked for: nothing, or a ref this roll never registered.
    """
    _source, definition, call, _reporter = _roll(tmp_path / "a", name="subject")
    value = call._construct_sugar()

    absent = call._ask_roll_for_occurrence(None, value)
    assert isinstance(absent, NothingToProject), absent

    _foreign_source, foreign_definition, _foreign_call, _foreign_reporter = _roll(
        tmp_path / "b", name="foreign", helper="helper", caller="caller"
    )
    foreign_ref = foreign_definition.ref
    assert foreign_ref is not definition.ref
    unanswered = call._ask_roll_for_occurrence(foreign_ref, value)
    assert isinstance(unanswered, ParserHandleLookupFailed), unanswered
    assert unanswered.ref is foreign_ref
    # It says WHICH lookup failed, so the reader is sent to the repair.
    assert "registered" in unanswered.reason

    # ABSENT and UNANSWERED are not the same value, and neither is spelled None.
    assert absent != unanswered
    assert absent is not None and unanswered is not None
    assert type(absent) in PARSER_HANDLE_PROJECTION_OUTCOMES
    assert type(unanswered) in PARSER_HANDLE_PROJECTION_OUTCOMES


def test_a_registered_ref_answers_with_this_rolls_typed_occurrence(
    tmp_path,
) -> None:
    _source, definition, call, _reporter = _roll(tmp_path, name="subject")
    value = call._construct_sugar()

    answered = call._ask_roll_for_occurrence(definition.ref, value)
    assert isinstance(answered, ParserHandleProjected), answered
    assert answered.occurrence is definition
    # ANSWERED never hands back the ref it was given dressed as an answer.
    assert answered.occurrence is not definition.ref


# ---------------------------------------------------------------------------
# THE SEAT -- which fault the refusal NAMES
# ---------------------------------------------------------------------------


def _sugar_with_unregistered_owner(tmp_path):
    """A CallSiteSugar whose frame-owner slot carries a foreign parser handle.

    This is the shape that reached canonicalization: ``expected_definition_ref``
    projected fine, and ``.expected_source_call_frame_owner`` -- seated from
    ``lexical_row.definition_occurrence_identity``, which IS a raw ``.ref`` --
    was never visited by any projection at all.
    """
    _source, definition, call, _reporter = _roll(tmp_path / "a", name="subject")
    _f_source, foreign_definition, _f_call, _f_reporter = _roll(
        tmp_path / "b", name="foreign"
    )
    value = call._construct_sugar()
    assert isinstance(value, CallSiteSugar)
    return (
        call,
        definition,
        foreign_definition.ref,
        replace(
            value,
            expected_definition_ref=definition.ref,
            expected_source_call_frame_owner=foreign_definition.ref,
        ),
    )


def test_the_refusal_names_the_failed_lookup_and_not_a_missing_category(
    tmp_path,
) -> None:
    """THE SPLIT, shown as two different sentences about the same handle.

    Arm 1: the handle goes through the projection door -- it refuses naming a
    FAILED LOOKUP and the exact slot.
    Arm 2: the identical handle is handed straight to canonicalization -- it
    refuses naming a MISSING CATEGORY.

    Both refusals are correct about their own question, and before this repair
    only the second one ever got said. Running BOTH arms is the point: a tooth
    that only asserted arm 1 could not tell a split from a rename.
    """
    call, _definition, handle, value = _sugar_with_unregistered_owner(tmp_path)

    with pytest.raises(BackendDefect) as projection_gap:
        call._project_constructed_value_for_testimony(value)
    projection_text = str(projection_gap.value)
    assert "parser handle projection FAILED" in projection_text
    assert ".expected_source_call_frame_owner" in projection_text
    assert "Call._project_constructed_value_for_testimony" in projection_text
    # The wrong fault is NOT named here.
    assert "unclassified constructed value category" not in projection_text

    with pytest.raises(ConstructedValueTestimonyNotWritten) as category_gap:
        call.reporter.present_construction(call, handle)
    category_text = str(category_gap.value)
    assert "unclassified constructed value category" in category_text
    assert "cpython_adapter._Handle" in category_text
    # ...and the failed lookup is not named THERE either. Two questions, two
    # answers; the defect was that only the second one was ever reachable.
    assert "parser handle projection FAILED" not in category_text


def test_the_gap_is_testified_through_the_roll_before_it_throws(tmp_path) -> None:
    """A refusal the census never sees is an instrument failure, not a row.

    Raising untestified would trade a loud measured row for a dead file, which
    is a LOSS OF LOUDNESS wearing a passing test.
    """
    call, _definition, _handle, value = _sugar_with_unregistered_owner(tmp_path)
    collector = call.reporter._delegate
    before = len(collector.gaps)

    with pytest.raises(BackendDefect):
        call._project_constructed_value_for_testimony(value)

    assert len(collector.gaps) == before + 1
    gap_node, gap_panic = collector.gaps[-1]
    assert gap_node is call
    assert "parser handle projection FAILED" in str(gap_panic)


def test_nothing_to_project_never_refuses(tmp_path) -> None:
    """ABSENT is not a fault. A call carrying no handles projects silently."""
    _source, _definition, call, _reporter = _roll(tmp_path, name="subject")
    value = replace(
        call._construct_sugar(),
        expected_definition_ref=None,
        expected_source_call_frame_owner=None,
        source_call_frame=None,
    )
    projected = call._project_constructed_value_for_testimony(value)
    assert projected is value


# ---------------------------------------------------------------------------
# THE SET IS CLOSED
# ---------------------------------------------------------------------------


def test_an_unrecognised_outcome_raises_instead_of_falling_through(
    tmp_path, monkeypatch
) -> None:
    """A fourth member with no arm must not reconcile as "no change".

    Falling through is exactly how the original nullable behaved, so a closed
    set that silently ignored an unknown member would have re-created the
    defect at one remove.
    """

    class _UnruledOutcome:
        pass

    _source, _definition, call, _reporter = _roll(tmp_path, name="subject")
    value = call._construct_sugar()
    assert isinstance(value, CallSiteSugar)

    monkeypatch.setattr(
        Call,
        "_ask_roll_for_occurrence",
        lambda self, ref, value: _UnruledOutcome(),
    )
    with pytest.raises(BackendDefect) as gap:
        call._project_constructed_value_for_testimony(value)
    assert "unrecognised parser-handle projection outcome" in str(gap.value)
    assert "_UnruledOutcome" in str(gap.value)


def test_a_roll_with_no_materialize_table_is_owed_nothing_not_refused(
    tmp_path,
) -> None:
    """NOT OWED is its own member, and this is the tooth that was missing.

    A first version of this repair folded "this roll seats no materialize
    table" into UNANSWERED. A unit tooth asserting that only the canonicalizing
    reporter reaches this projection PASSED -- and was true about the classes
    while being false about production. The pandas slice refuted it: 61 files
    that measured cleanly became instrument failures, because rolls with no
    table reach here throughout the enrolled corpus.

    So the claim is now pinned where it broke: a roll with no table must be
    handed its value back UNTOUCHED and must never refuse.
    """
    _source, definition, call, _reporter = _roll(tmp_path, name="subject")
    value = call._construct_sugar()
    assert isinstance(value, CallSiteSugar)

    plain = CollectingReporter()
    assert not hasattr(plain, "materialized_node_for_ref")
    object.__setattr__(call, "reporter", plain)

    outcome = call._ask_roll_for_occurrence(definition.ref, value)
    assert isinstance(outcome, RollProjectsNothing), outcome
    # NOT OWED is not ABSENT and not UNANSWERED.
    assert not isinstance(outcome, (NothingToProject, ParserHandleLookupFailed))
    # And it refuses NOTHING: the value comes back exactly as it went in.
    assert call._project_constructed_value_for_testimony(value) is value
