"""Structural match patterns and guards are built (#7757 item 7, after #8009).

A sequence (`case [a, *rest]:`), mapping (`case {"k": v}:`) or class
(`case Point(x=0):`) pattern is a selection over the subject -- its type,
length and key tests and each sub-pattern's test of the subject's projection,
through the floor's own operations -- plus the case's capture keys
(``Match.substitute``) bound to those projections.  A guard is evaluated after
the captures bind and joins the case's selection.  A test the floor does not
decide on an opaque subject is refused by name (``undecided``).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    DictValue,
    ListValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.object_field import ObjectField
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_py_tests.outcome.exit_set import _is_false
from sugar_lift_py_tests.sugar.match_sugar import (
    CapturePatternSpec,
    ClassPatternSpec,
    MappingPatternSpec,
    MatchSugar,
    SequencePatternSpec,
    ValuePatternSpec,
    _CompleteValueSugar,
    match_pattern,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef, FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

SITE = "match-structural-patterns"


def _source(source: str, context=None) -> SourceFile:
    context = context or TreeConstructionContextV1.for_source_call_construction()
    return SourceFile(
        (source, "match_structural.py", blake3_512_of(source.encode())),
        construction_context=context,
    )


def _match(source: str) -> MatchSugar:
    """The match statement ``f`` opens with, as constructed."""
    function = next(
        node
        for node in _source(source).nodes()
        if isinstance(node, FunctionDef) and node.name == "f"
    )
    statement = function.sugar().statements[0]
    assert isinstance(statement, MatchSugar), statement
    return statement


def _matched(outcome):
    matched = outcome.completed_value()
    assert matched is not None, outcome
    return matched


def _opaque():
    return SymbolicValue(ctor("test.opaque_subject", []))


def _reduced(statement: MatchSugar, subject):
    """``statement`` over a subject already reduced to ``subject``."""
    return replace(statement, subject=_CompleteValueSugar(subject, SITE)).desugar(
        ReduceContext.root(owner="test_match_structural_patterns")
    )


def _returned(exits) -> list:
    """What every live completed arm of ``exits`` returns."""
    returned = []
    for face in exits.exits:
        if not isinstance(face, Completed) or _is_false(face.guard):
            continue
        pending = [face.value]
        while pending:
            value = pending.pop()
            if isinstance(value, ReturnValue):
                returned.append(value.value)
                continue
            for field in ("entries", "statements"):
                pending.extend(getattr(value, field, None) or ())
    return returned


# -- sequence ------------------------------------------------------------------

SEQUENCE = (
    "def f(s):\n"
    "    match s:\n"
    "        case [a, *rest]:\n"
    "            return rest\n"
    "    return None\n"
)


def test_a_sequence_pattern_binds_its_item_and_its_star() -> None:
    pattern = _match(SEQUENCE).cases[0].pattern
    assert isinstance(pattern, SequencePatternSpec)
    assert pattern.has_star
    (first,) = pattern.before
    assert isinstance(first, CapturePatternSpec)
    subject = TupleValue((TermValue(1), TermValue(2), TermValue(3)))
    matched = _matched(match_pattern(pattern, subject, SITE, None))
    assert matched.matched
    binds = dict(matched.binds)
    assert binds[first.key] == TermValue(1)
    # A star captures a list, from a tuple too.
    rest = binds[pattern.star_key]
    assert type(rest) is ListValue
    assert rest.elements == (TermValue(2), TermValue(3))


def test_a_sequence_pattern_misses_a_shorter_sequence_and_a_string() -> None:
    pattern = _match(SEQUENCE).cases[0].pattern
    assert not _matched(match_pattern(pattern, TupleValue(()), SITE, None)).matched
    # A ``str`` is never a sequence to a pattern.
    assert not _matched(match_pattern(pattern, StringValue("ab"), SITE, None)).matched


def test_a_sequence_test_on_an_opaque_subject_is_undecided() -> None:
    pattern = _match(SEQUENCE).cases[0].pattern
    with pytest.raises(SugarNotWritten) as excinfo:
        match_pattern(pattern, _opaque(), SITE, None)
    assert excinfo.value.observed.startswith("undecided")


def test_the_case_body_reads_the_star_through_its_key() -> None:
    returned = _returned(
        _reduced(
            _match(SEQUENCE), TupleValue((TermValue(1), TermValue(2), TermValue(3)))
        )
    )
    assert len(returned) == 1
    assert type(returned[0]) is ListValue
    assert returned[0].elements == (TermValue(2), TermValue(3))


# -- mapping -------------------------------------------------------------------

MAPPING = (
    "def f(s):\n"
    "    match s:\n"
    '        case {"k": v}:\n'
    "            return v\n"
    "    return None\n"
)


def test_a_mapping_pattern_binds_the_value_at_its_key() -> None:
    pattern = _match(MAPPING).cases[0].pattern
    assert isinstance(pattern, MappingPatternSpec)
    (capture,) = pattern.patterns
    assert isinstance(capture, CapturePatternSpec)
    subject = fresh(DictValue, ((StringValue("k"), TermValue(5)),))
    matched = _matched(match_pattern(pattern, subject, SITE, None))
    assert matched.matched
    assert dict(matched.binds) == {capture.key: TermValue(5)}


def test_a_mapping_pattern_misses_a_missing_key_and_a_sequence() -> None:
    pattern = _match(MAPPING).cases[0].pattern
    missing = fresh(DictValue, ((StringValue("j"), TermValue(5)),))
    assert not _matched(match_pattern(pattern, missing, SITE, None)).matched
    assert not _matched(match_pattern(pattern, TupleValue(()), SITE, None)).matched


def test_a_mapping_test_on_an_opaque_subject_is_undecided() -> None:
    pattern = _match(MAPPING).cases[0].pattern
    with pytest.raises(SugarNotWritten) as excinfo:
        match_pattern(pattern, _opaque(), SITE, None)
    assert excinfo.value.observed.startswith("undecided")


# -- class ---------------------------------------------------------------------

POINT = (
    "class Point:\n"
    "    pass\n"
    "def f(p):\n"
    "    match p:\n"
    "        case Point(x=0):\n"
    "            return 1\n"
    "    return 2\n"
)


def _point():
    """``Point`` as its class statement constructs it."""
    tree = _source(POINT, TreeConstructionContextV1.for_test_without_workspace())
    node = next(node for node in tree.root.body if isinstance(node, ClassDef))
    return (
        node.sugar()
        .desugar(ReduceContext.root(owner="test_match_structural_patterns"))
        .completed_value()
    )


def test_a_class_pattern_is_built_with_its_keyword() -> None:
    pattern = _match(POINT).cases[0].pattern
    assert isinstance(pattern, ClassPatternSpec)
    assert pattern.positional == ()
    ((attr, sub),) = pattern.keywords
    assert attr == "x"
    assert isinstance(sub, ValuePatternSpec)


def test_a_class_pattern_tests_the_instance_and_its_attribute() -> None:
    point = _point()
    pattern = ClassPatternSpec(
        _CompleteValueSugar(point, SITE),
        (),
        (("x", ValuePatternSpec(_CompleteValueSugar(TermValue(0), SITE))),),
    )
    receiver = point.fresh_receiver("point-receiver")
    at_zero = replace(receiver, fields=(ObjectField("x", TermValue(0)),))
    at_one = replace(receiver, fields=(ObjectField("x", TermValue(1)),))
    assert _matched(match_pattern(pattern, at_zero, SITE, None)).matched
    assert not _matched(match_pattern(pattern, at_one, SITE, None)).matched
    # Whether an int is an instance of a source class is not decided here.
    with pytest.raises(SugarNotWritten) as excinfo:
        match_pattern(pattern, TermValue(0), SITE, None)
    assert excinfo.value.observed.startswith("undecided")


# -- guard ---------------------------------------------------------------------

GUARD = (
    "def f(s):\n"
    "    match s:\n"
    "        case [a, b] if a > b:\n"
    "            return a\n"
    "        case _:\n"
    "            return 0\n"
)


def test_a_guard_reads_the_captures_and_joins_the_selection() -> None:
    statement = _match(GUARD)
    assert statement.cases[0].guard is not None
    descending = _reduced(statement, TupleValue((TermValue(3), TermValue(1))))
    ascending = _reduced(statement, TupleValue((TermValue(1), TermValue(3))))
    assert _returned(descending) == [TermValue(3)]
    # The guard is false: the next case is selected.
    assert _returned(ascending) == [TermValue(0)]


def test_a_value_pattern_guard_is_built() -> None:
    statement = _match(
        "def f(z):\n    match z:\n        case 1 if z > 0:\n            return z\n"
    )
    assert statement.cases[0].guard is not None
    assert statement.cases[0].pattern is None
