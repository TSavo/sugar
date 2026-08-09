"""RED: CPython call handles must materialize before construction testimony."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph
from sugar_source_tree.backend import materialize
from sugar_source_tree.binding_state import (
    _callee_definition_by_name_in_its_unit,
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
)
from sugar_source_tree.nodes import Call, ClassDef, FunctionDef
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


# ---------------------------------------------------------------------------
# A cross-FILE callee inside the enrolled population is not a fault
# ---------------------------------------------------------------------------


def _two_files_one_roll(tmp_path):
    """Two units materialized through ONE reporter roll.

    The cross-file case cannot be built from a single file, and it must share a
    reporter: a definition materialized by a DIFFERENT reporter is a genuinely
    unregistered ref and is refused by `definition-ref-not-materialized`, which
    is a different fault and must stay one.
    """
    helper_path = tmp_path / "callee_unit.py"
    helper_path.write_text("def find_level(value):\n    return value\n")
    caller_path = tmp_path / "caller_unit.py"
    caller_path.write_text("def apply(value):\n    return find_level(value)\n")

    collector = CollectingReporter()
    helper_source = SourceFile.from_path(helper_path, reporter=collector)
    caller_source = SourceFile.from_path(caller_path, reporter=collector)
    # ONE roll over both units -- `_testimony_root` mints a fresh reporter per
    # source, and two rolls would make the callee legitimately unregistered.
    testimony = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(caller_source.unit.source_cid)
    )
    helper_root = materialize(helper_source.unit, helper_source.root.ref, testimony)
    caller_root = materialize(caller_source.unit, caller_source.root.ref, testimony)

    definition = next(
        node
        for node in helper_root.walk()
        if isinstance(node, FunctionDef) and node.name == "find_level"
    )
    call = next(
        node
        for node in caller_root.walk()
        if isinstance(node, Call) and node.segment() == "find_level(value)"
    )
    assert definition.unit.source_cid != call.unit.source_cid
    return definition, call, testimony


def test_a_cross_file_enrolled_callee_is_not_an_identity_fault(tmp_path) -> None:
    """`_config/config.py` calling `util/_exceptions.find_stack_level`.

    82 rows of the frontier sat here. The guard demanded the callee be defined
    in the CALLER's file, which no real corpus can satisfy -- that described
    our instrument, not a defect in pandas.
    """
    definition, call, reporter = _two_files_one_roll(tmp_path)
    truthful = call._project_constructed_value_for_testimony(call._construct_sugar())
    frame = definition.source_visible_call_frame()

    fault = reporter._source_call_identity_fault(
        call, truthful, definition, definition, truthful.call_occurrence, frame
    )
    assert fault is None, fault


def test_an_unauthenticated_callee_unit_still_refuses_by_its_own_name(
    tmp_path,
) -> None:
    """The boundary that must not move.

    "Foreign but authenticated" and "foreign and unknown" must never collapse
    into one outcome. A unit carrying no content address is refused, and it is
    refused under a DIFFERENT name than the cross-file case above returns.
    """
    definition, call, reporter = _two_files_one_roll(tmp_path)
    truthful = call._project_constructed_value_for_testimony(call._construct_sugar())
    frame = definition.source_visible_call_frame()
    object.__setattr__(definition.unit, "source_cid", "")

    fault = reporter._source_call_identity_fault(
        call, truthful, definition, definition, truthful.call_occurrence, frame
    )
    assert fault == "definition-unit-unauthenticated"


def test_an_opaque_callee_keeps_its_own_separate_name(tmp_path) -> None:
    """The other half of the same boundary, measured on the real corpus.

    Of 57 cross-file arrivals at this guard in the stride-8 slice, 7 were
    unmaterialized `_Handle`s. They are caught ABOVE the unit terms, so
    relaxing the same-unit demand cannot let one through.
    """
    definition, call, reporter = _two_files_one_roll(tmp_path)
    truthful = call._project_constructed_value_for_testimony(call._construct_sugar())

    class _OpaqueHandle:
        """Stands where a raw parser handle arrives: no unit, no fragment."""

    fault = reporter._source_call_identity_fault(
        call, truthful, _OpaqueHandle(), definition, truthful.call_occurrence, None
    )
    assert fault == "definition-not-a-functiondef"


def test_the_frame_site_term_is_keyed_on_the_definitions_unit(tmp_path) -> None:
    """A frame describes the CALLEE's definition, so its site lives in the
    callee's file. Keying it on the caller's unit was the same-unit demand
    wearing a second name -- it refused every cross-file call a second time."""
    definition, call, reporter = _two_files_one_roll(tmp_path)
    truthful = call._project_constructed_value_for_testimony(call._construct_sugar())
    frame = definition.source_visible_call_frame()

    # The callee's own site passes ...
    assert (
        reporter._source_call_identity_fault(
            call, truthful, definition, definition, truthful.call_occurrence, frame
        )
        is None
    )
    # ... and a site belonging to neither unit is still refused, by name.
    foreign_site = replace(frame.definition_site, source_cid="blake3-512:" + "00" * 64)
    assert (
        reporter._source_call_identity_fault(
            call,
            truthful,
            definition,
            definition,
            truthful.call_occurrence,
            replace(frame, definition_site=foreign_site),
        )
        == "frame-definition-site-foreign"
    )


# ---------------------------------------------------------------------------
# THE FALSIFIABILITY GATE: the third authority must be able to REFUSE
# ---------------------------------------------------------------------------


def _shadowing_callee_unit(tmp_path):
    """A callee unit where the callee's NAME is also bound nested.

    The module binding of `find_level` is the top-level def. The nested def
    inside `other` shares the name and is a DIFFERENT span and different text.
    """
    helper_path = tmp_path / "shadow_callee.py"
    helper_path.write_text(
        "def find_level(value):\n"
        "    return value\n"
        "\n"
        "def other(value):\n"
        "    def find_level(inner):\n"
        "        return inner + 1\n"
        "    return find_level(value)\n"
    )
    caller_path = tmp_path / "shadow_caller.py"
    caller_path.write_text("def apply(value):\n    return find_level(value)\n")

    collector = CollectingReporter()
    helper_source = SourceFile.from_path(helper_path, reporter=collector)
    caller_source = SourceFile.from_path(caller_path, reporter=collector)
    testimony = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(caller_source.unit.source_cid)
    )
    helper_root = materialize(helper_source.unit, helper_source.root.ref, testimony)
    caller_root = materialize(caller_source.unit, caller_source.root.ref, testimony)

    definitions = [
        node
        for node in helper_root.walk()
        if isinstance(node, FunctionDef) and node.name == "find_level"
    ]
    assert len(definitions) == 2, definitions
    top_level = min(definitions, key=lambda d: d.line_col_span().start_line)
    nested = max(definitions, key=lambda d: d.line_col_span().start_line)
    call = next(
        node
        for node in caller_root.walk()
        if isinstance(node, Call) and node.segment() == "find_level(value)"
    )
    return top_level, nested, call, testimony


def test_the_third_authority_accepts_the_true_cross_file_callee(tmp_path) -> None:
    """The truthful arm of the twin, so the refusal below is discrimination
    and not a guard that refuses everything."""
    top_level, _nested, call, reporter = _shadowing_callee_unit(tmp_path)
    truthful = call._project_constructed_value_for_testimony(call._construct_sugar())
    frame = top_level.source_visible_call_frame()

    # Exactly what `present_construction` now supplies: the caller's unit has
    # no answer for a cross-file callee, so the third authority answers.
    resolved = _callee_definition_by_name_in_its_unit(top_level)
    # Not `is`: the module binding table holds an equal-but-distinct instance
    # for the same span. The SEAL is the identity here, which is the whole
    # point -- content, not object address.
    assert resolved.fragment.seal() == top_level.fragment.seal()
    assert (
        reporter._source_call_identity_fault(
            call, truthful, top_level, resolved, truthful.call_occurrence, frame
        )
        is None
    )


def test_a_shadowed_same_name_definition_is_REFUSED(tmp_path) -> None:
    """THE LYING TWIN.

    A nested definition sharing the callee's name is handed over as the
    callee. Same name, same unit, same file -- everything a name-only check
    would accept. The callee's own source says the module binding of that name
    is somewhere else entirely, and the seal over file+cid+span+text is what
    catches it.

    If this ever passes, the third authority is a tautology and must be torn
    out: it would convert 81 loud rows into 81 silent ones.
    """
    _top_level, nested, call, reporter = _shadowing_callee_unit(tmp_path)
    truthful = call._project_constructed_value_for_testimony(call._construct_sugar())
    frame = nested.source_visible_call_frame()

    # The third authority does NOT return the nested impostor: it reads the
    # unit's module binding table, which names the top-level definition.
    resolved = _callee_definition_by_name_in_its_unit(nested)
    assert resolved.fragment.seal() != nested.fragment.seal(), (
        "the authority accepted the impostor"
    )

    fault = reporter._source_call_identity_fault(
        call, truthful, nested, resolved, truthful.call_occurrence, frame
    )
    assert fault == "resolved-seal-mismatch", fault


# ---------------------------------------------------------------------------
# A CLASS is a legitimate callee -- and the same gate applies to it
# ---------------------------------------------------------------------------


def _shadowing_allocation_unit(tmp_path):
    """A callee unit where an ALLOCATION callee's name is also bound nested.

    ``Boom`` is a module-scope exception class with no ``__init__`` -- the
    exact shape of ``pandas._config.config.OptionError``. The nested class
    inside ``other`` shares the name, has a different span and different text,
    and is the lie.
    """
    helper_path = tmp_path / "shadow_allocation_callee.py"
    helper_path.write_text(
        "class Boom(ValueError):\n"
        '    """The module-scope allocation callee."""\n'
        "\n"
        "\n"
        "def other(value):\n"
        "    class Boom(ValueError):\n"
        '        """A NESTED class of the same name -- the impostor."""\n'
        "\n"
        "    return Boom\n"
    )
    caller_path = tmp_path / "shadow_allocation_caller.py"
    caller_path.write_text("def apply(value):\n    raise Boom(value)\n")

    collector = CollectingReporter()
    helper_source = SourceFile.from_path(helper_path, reporter=collector)
    caller_source = SourceFile.from_path(caller_path, reporter=collector)
    testimony = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(caller_source.unit.source_cid)
    )
    helper_root = materialize(helper_source.unit, helper_source.root.ref, testimony)
    caller_root = materialize(caller_source.unit, caller_source.root.ref, testimony)

    definitions = [
        node
        for node in helper_root.walk()
        if isinstance(node, ClassDef) and node.name == "Boom"
    ]
    assert len(definitions) == 2, definitions
    top_level = min(definitions, key=lambda d: d.line_col_span().start_line)
    nested = max(definitions, key=lambda d: d.line_col_span().start_line)
    call = next(
        node
        for node in caller_root.walk()
        if isinstance(node, Call) and node.segment() == "Boom(value)"
    )
    return top_level, nested, call, testimony


def test_a_class_callee_carries_a_derivable_constructor_law(tmp_path) -> None:
    """The premise this admission rests on, measured rather than assumed.

    ``Boom`` defines no ``__init__``, so the claim under test is that its
    constructor law is derivable IN POPULATION -- from its own body plus the
    authenticated base graph -- and not a body sugar cannot see. If this ever
    goes red, admitting a ClassDef below stops being sound and the citation
    road is the correct repair after all.
    """
    top_level, _nested, _call, _reporter = _shadowing_allocation_unit(tmp_path)
    assert not any(
        getattr(member, "name", None) == "__init__" for member in top_level.body
    )
    assert top_level._inherits_default_exception_constructor() is True
    frame = top_level.source_visible_constructor_frame()
    assert frame.parameters == ("args",), frame.parameters
    assert frame.parameter_kinds == ("vararg",), frame.parameter_kinds
    assert frame.owner is top_level


def test_the_third_authority_accepts_the_true_allocation_callee(tmp_path) -> None:
    """The truthful arm, so the refusal below is discrimination."""
    top_level, _nested, call, reporter = _shadowing_allocation_unit(tmp_path)
    truthful = call._project_constructed_value_for_testimony(call._construct_sugar())
    frame = top_level.source_visible_constructor_frame()

    resolved = _callee_definition_by_name_in_its_unit(top_level)
    assert resolved.fragment.seal() == top_level.fragment.seal()
    assert (
        reporter._source_call_identity_fault(
            call, truthful, top_level, resolved, truthful.call_occurrence, frame
        )
        is None
    )


def test_a_shadowed_same_name_CLASS_is_REFUSED(tmp_path) -> None:
    """THE LYING TWIN, allocation arm.

    A nested class sharing the callee's name is handed over as the callee.
    Same name, same unit, same file, same bases -- everything a name-only or
    kind-only check would accept. Admitting ClassDef must not cost the seal.

    If this ever passes, the admission is a tautology and must be torn out: it
    would convert 78 loud rows into 78 silent ones.
    """
    _top_level, nested, call, reporter = _shadowing_allocation_unit(tmp_path)
    truthful = call._project_constructed_value_for_testimony(call._construct_sugar())
    frame = nested.source_visible_constructor_frame()

    resolved = _callee_definition_by_name_in_its_unit(nested)
    assert resolved.fragment.seal() != nested.fragment.seal(), (
        "the authority accepted the impostor"
    )

    fault = reporter._source_call_identity_fault(
        call, truthful, nested, resolved, truthful.call_occurrence, frame
    )
    assert fault == "resolved-seal-mismatch", fault


def test_a_class_resolving_to_a_function_of_the_same_name_is_REFUSED(
    tmp_path,
) -> None:
    """The kind disagreement gets its OWN name.

    The two authorities can disagree about WHAT a name is, not only about
    where it lives. Lumping that into the seal term would print a fault that
    names the wrong repair.
    """
    top_level, _nested, call, reporter = _shadowing_allocation_unit(tmp_path)
    truthful = call._project_constructed_value_for_testimony(call._construct_sugar())
    frame = top_level.source_visible_constructor_frame()
    _source, function_definition, _fn_call, _fn_reporter = _ordinary_call(
        tmp_path, helper="Boom", caller="apply_function"
    )
    assert isinstance(function_definition, FunctionDef)

    fault = reporter._source_call_identity_fault(
        call,
        truthful,
        top_level,
        function_definition,
        truthful.call_occurrence,
        frame,
    )
    assert fault == "resolved-definition-kind-mismatch", fault


def test_an_opaque_allocation_callee_still_refuses_by_its_own_name(
    tmp_path,
) -> None:
    """The boundary that must not move.

    Admitting ClassDef must not admit a callee with no readable definition at
    all. An unmaterialized handle is still `definition-not-a-functiondef`.
    """
    top_level, _nested, call, reporter = _shadowing_allocation_unit(tmp_path)
    truthful = call._project_constructed_value_for_testimony(call._construct_sugar())

    class _OpaqueHandle:
        """Stands where a raw parser handle arrives: no unit, no fragment."""

    fault = reporter._source_call_identity_fault(
        call, truthful, _OpaqueHandle(), top_level, truthful.call_occurrence, None
    )
    assert fault == "definition-not-a-functiondef"


def test_a_class_definition_shows_up_on_the_roll(tmp_path) -> None:
    """A NODE OFF THE ROLL.

    ``Node.__post_init__`` states the law: registering in the constructor is
    what makes ``cls(...)`` show up on the roll, and there is no way to new a
    node without it. ``ClassDef`` overrode that method and never called it, so
    every class in the corpus was constructed unregistered -- and
    ``definition-ref-not-materialized`` was unsatisfiable for every allocation
    callee no matter what the identity guard admitted.

    This is about the ROLL, not about the guard: a class must be on it for the
    same reason a function is.
    """
    top_level, nested, _call, reporter = _shadowing_allocation_unit(tmp_path)
    for definition in (top_level, nested):
        assert reporter.materialized_node_for_ref(definition.ref) is not None, (
            f"ClassDef at line {definition.line_col_span().start_line} is off the roll"
        )
    kinds = {type(node).__name__ for node in reporter._materialized_by_ref.values()}
    assert "ClassDef" in kinds, sorted(kinds)


def test_an_allocation_handle_is_projected_to_its_typed_class_occurrence(
    tmp_path,
) -> None:
    """The projection arm, which no other tooth reaches.

    On the production path an allocation call carries
    ``expected_definition_ref=bound_frame.owner.ref`` -- a raw parser handle,
    not a typed node. Every other allocation tooth hands the guard a typed
    definition directly and so routes AROUND the projection; a mutation that
    dropped its ClassDef arm failed nothing at all. This is that tooth.
    """
    top_level, _nested, call, reporter = _shadowing_allocation_unit(tmp_path)
    constructed = call._construct_sugar()
    # Exactly what the preconstruction branch installs.
    with_handle = replace(constructed, expected_definition_ref=top_level.ref)
    assert not isinstance(with_handle.expected_definition_ref, ClassDef)

    projected = call._project_constructed_value_for_testimony(with_handle)

    assert isinstance(projected.expected_definition_ref, ClassDef), (
        projected.expected_definition_ref
    )
    assert (
        projected.expected_definition_ref.fragment.seal()
        == top_level.fragment.seal()
    )
    # And the projected occurrence is one the guard can actually admit: a raw
    # handle stops at term 1, a projected class reaches the seal join.
    assert reporter._source_call_identity_fault(
        call,
        projected,
        with_handle.expected_definition_ref,
        top_level,
        projected.call_occurrence,
        top_level.source_visible_constructor_frame(),
    ) == "definition-not-a-functiondef"
