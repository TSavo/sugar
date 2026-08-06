"""RED: CPython call handles must materialize before construction testimony."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph
from sugar_source_tree.backend import materialize
from sugar_source_tree.binding_state import (
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
)
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.panic import ConstructedValueTestimonyNotWritten
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.tree import SourceFile


def _testimony_root(source: SourceFile, collector: CollectingReporter):
    reporter = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(source.unit.source_cid)
    )
    return materialize(source.unit, source.root.ref, reporter), reporter


def _enum_call() -> tuple[SourceFile, FunctionDef, Call]:
    graph = DependencyArtifactGraph.authenticate_stdlib_module("enum")
    module = graph.modules["enum"]
    reporter = CollectingReporter()
    source = SourceFile(
        (module.source, module.source_seat, module.source_cid), reporter=reporter
    )
    root, _testimony = _testimony_root(source, reporter)
    definition = next(
        node
        for node in root.walk()
        if isinstance(node, FunctionDef) and node.name == "_is_single_bit"
    )
    call = next(
        node
        for node in root.walk()
        if isinstance(node, Call)
        and node.line_col_span().start_line == 293
        and node.line_col_span().start_col == 19
    )
    assert call.segment() == "_is_single_bit(value)"
    return source, definition, call


def _ordinary_call(tmp_path, *, helper: str, caller: str):
    path = tmp_path / f"{helper}.py"
    path.write_text(
        f"def {helper}(value):\n"
        "    return value\n\n"
        f"def {caller}(value):\n"
        f"    return {helper}(value)\n"
    )
    reporter = CollectingReporter()
    source = SourceFile.from_path(path, reporter=reporter)
    root, testimony = _testimony_root(source, reporter)
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
    return source, definition, call, testimony


@pytest.mark.parametrize(
    "case",
    ("authenticated-enum", "unrelated-renamed-source"),
)
def test_parser_call_definition_is_materialized_before_reporter_testimony(
    case, tmp_path
) -> None:
    if case == "authenticated-enum":
        source, definition, call = _enum_call()
    else:
        source, definition, call, _reporter = _ordinary_call(
            tmp_path, helper="unrelated_predicate", caller="apply_predicate"
        )

    constructed = call.sugar()

    # The adapter handle is only parser machinery.  The semantic construction
    # carries the exact typed definition occurrence materialized by this unit.
    assert constructed.expected_definition_ref is definition
    assert definition.unit is source.unit
    assert definition.fragment.unit is call.fragment.unit
    assert definition.fragment.seal().source_cid == source.unit.source_cid
    assert definition.kind == "FunctionDef"


def test_raw_or_reminted_parser_handle_never_becomes_semantic_testimony(
    tmp_path,
) -> None:
    _source, _definition, call = _enum_call()
    pre_reporter = call._construct_sugar()
    raw_handle = pre_reporter.expected_definition_ref
    _reminted_source, _reminted_definition, reminted_call, reminted_reporter = (
        _ordinary_call(tmp_path, helper="_is_single_bit", caller="other_call")
    )
    reminted_handle = reminted_call._construct_sugar().expected_definition_ref
    assert reminted_handle is not raw_handle

    # The current offender is retained only to prove the adapter object itself
    # is not the category to admit.  Both the raw occurrence and an independently
    # parsed same-spelling occurrence remain loud at the reporter membrane.
    with pytest.raises(ConstructedValueTestimonyNotWritten) as raw_gap:
        call.reporter.present_construction(call, raw_handle)
    assert "unclassified constructed value category" in str(raw_gap.value)
    assert "cpython_adapter._Handle" in str(raw_gap.value)
    with pytest.raises(ConstructedValueTestimonyNotWritten) as reminted_gap:
        reminted_reporter.present_construction(reminted_call, reminted_handle)
    assert "cpython_adapter._Handle" in str(reminted_gap.value)


@pytest.mark.parametrize(
    "axis",
    ("foreign-source", "wrong-node", "wrong-kind", "method-shaped"),
)
def test_call_definition_testimony_rejects_foreign_or_wrong_occurrence(
    axis, tmp_path
) -> None:
    _source, definition, call, reporter = _ordinary_call(
        tmp_path, helper="predicate", caller="apply"
    )
    truthful = call._construct_sugar()
    foreign_source, foreign_definition, foreign_call, _foreign_reporter = (
        _ordinary_call(tmp_path, helper="predicate", caller="foreign_apply")
    )
    assert foreign_source.unit.source_cid != call.unit.source_cid

    if axis == "foreign-source":
        lie = foreign_definition
    elif axis == "wrong-node":
        lie = foreign_call
    elif axis == "wrong-kind":
        lie = definition.body[0]
    else:
        lie = definition.sugar

    substituted = replace(truthful, expected_definition_ref=lie)
    with pytest.raises(ConstructedValueTestimonyNotWritten) as gap:
        reporter.present_construction(call, substituted)
    assert "CollectingReporter.present_construction" in str(gap.value)
    assert call.unit.filename in str(gap.value)


# ---------------------------------------------------------------------------
# TEN FAULTS, NOT ONE: the identity guard names the term it refused on
# ---------------------------------------------------------------------------


def test_every_identity_refusal_names_which_term_refused(tmp_path) -> None:
    """A countable row is not an actionable one.

    All four axes below are genuinely different defects asking for different
    repairs. If they all print the same sentence, the board can count them and
    nobody can fix them.
    """
    _source, definition, call, reporter = _ordinary_call(
        tmp_path, helper="predicate", caller="apply"
    )
    truthful = call._construct_sugar()
    foreign_source, foreign_definition, foreign_call, _foreign = _ordinary_call(
        tmp_path, helper="predicate", caller="foreign_apply"
    )
    assert foreign_source.unit.source_cid != call.unit.source_cid

    seen = set()
    for lie in (
        foreign_definition,
        foreign_call,
        definition.body[0],
        definition.sugar,
    ):
        substituted = replace(truthful, expected_definition_ref=lie)
        with pytest.raises(ConstructedValueTestimonyNotWritten) as gap:
            reporter.present_construction(call, substituted)
        named = [
            term
            for term in ConstructionTestimonyReporterV1.SOURCE_CALL_IDENTITY_TERMS
            if term in str(gap.value)
        ]
        # Exactly one term, never zero (lumped) and never several (ambiguous).
        assert len(named) == 1, (named, str(gap.value))
        seen.add(named[0])
    # The four lies are not all one fault wearing four costumes.
    assert len(seen) > 1, seen


def test_the_seal_term_is_unreachable_without_a_resolved_definition(tmp_path) -> None:
    """The fragility this guard used to carry.

    ``resolved_definition.fragment`` raises AttributeError on None, so as a
    flat ``or`` chain the guard was safe only because the preceding
    isinstance term short-circuited first. Transposing two neighbouring lines
    would have turned a countable construction panic into an INSTRUMENT
    FAILURE -- a census hole, not a census row. The precondition must hold
    structurally, not by luck of ordering.
    """
    _source, _definition, call, reporter = _ordinary_call(
        tmp_path, helper="predicate", caller="apply"
    )
    # NOT ``call.sugar()``. On this context-less open, ``call_occurrence`` is
    # minted only under a TreeConstructionContextV1 while the guard compares it
    # unconditionally, so the truthful path already refuses with
    # ``call-occurrence-mismatch`` (a red that predates this change and is
    # tracked separately). Riding on it would make this tooth report that
    # defect instead of the one it is here to catch.
    truthful = call._project_constructed_value_for_testimony(call._construct_sugar())
    definition = truthful.expected_definition_ref
    call_occurrence = truthful.call_occurrence
    frame = truthful.source_call_frame

    # The tooth is only worth anything if it REACHES the seal term. Prove the
    # earlier terms pass first -- otherwise this returns at term 1 and would
    # stay green against exactly the transposition it claims to catch.
    assert (
        reporter._source_call_identity_fault(
            call, truthful, definition, definition, call_occurrence, frame
        )
        is None
    )

    class _NotADefinition:
        """No ``.fragment``: touching the seal term raises AttributeError."""

    for resolved in (None, _NotADefinition()):
        fault = reporter._source_call_identity_fault(
            call, truthful, definition, resolved, call_occurrence, frame
        )
        # It refuses, by name, WITHOUT reaching the term that would raise.
        assert fault == "resolved-not-a-functiondef"


def test_the_named_term_set_is_closed_over_the_body() -> None:
    """A term added to the body without a name is a silent lump reappearing."""
    import inspect
    import re

    body = inspect.getsource(
        ConstructionTestimonyReporterV1._source_call_identity_fault
    )
    # Only the docstring and the returns quote strings in this function.
    returned = set(re.findall(r'return "([a-z-]+)"', body))
    assert returned == set(
        ConstructionTestimonyReporterV1.SOURCE_CALL_IDENTITY_TERMS
    ), returned.symmetric_difference(
        ConstructionTestimonyReporterV1.SOURCE_CALL_IDENTITY_TERMS
    )
