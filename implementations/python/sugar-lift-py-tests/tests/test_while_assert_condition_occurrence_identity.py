"""Control conditions own one source occurrence, distinct from body sites."""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import RaiseValue
from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Assert, Compare, While
from sugar_source_tree.tree import SourceFile


SOURCE = (
    "def control(left, right):\n"
    "    while left < right:\n"
    "        assert left < right\n"
)


def _tree(source: str = SOURCE) -> SourceFile:
    return SourceFile(
        (source, "while-assert-occurrence.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _halt_occurrence(compare: Compare) -> str:
    outcome = compare.sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
    assert len(halted) == 1
    assert isinstance(halted[0].effect.occurrence_id, str) and ":" in halted[0].effect.occurrence_id, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted[0].effect.occurrence_id!r}"
    )
    return halted[0].effect.occurrence_id


def _comparisons() -> tuple[Compare, Compare]:
    tree = _tree()
    loop = next(node for node in tree.nodes() if isinstance(node, While))
    assertion = next(node for node in tree.nodes() if isinstance(node, Assert))
    assert isinstance(loop.test, Compare)
    assert isinstance(assertion.test, Compare)
    return loop.test, assertion.test


def test_while_condition_mints_one_stable_authenticated_occurrence() -> None:
    condition, _ = _comparisons()
    first = _halt_occurrence(condition)
    repeated = _halt_occurrence(condition)

    expected = str(condition.sugar().site)
    assert first == expected
    assert repeated == expected


def test_while_condition_occurrence_is_distinct_from_body_occurrences() -> None:
    condition, body_assertion = _comparisons()
    condition_occurrence = _halt_occurrence(condition)
    body_occurrence = _halt_occurrence(body_assertion)

    assert condition_occurrence != body_occurrence


def test_assert_condition_mints_one_stable_authenticated_occurrence() -> None:
    _, assertion = _comparisons()
    first = _halt_occurrence(assertion)
    repeated = _halt_occurrence(assertion)

    expected = str(assertion.sugar().site)
    assert first == expected
    assert repeated == expected


def test_assert_condition_halt_keeps_its_condition_occurrence() -> None:
    tree = _tree("def check():\n    assert None < 1\n")
    assertion = next(node for node in tree.nodes() if isinstance(node, Assert))
    assert isinstance(assertion.test, Compare)
    condition_site = assertion.test.sugar().site
    outcome = assertion.sugar().desugar(None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.occurrence_id == str(condition_site)


def test_identical_condition_and_body_operands_do_not_collapse_occurrences() -> None:
    condition, assertion = _comparisons()

    assert condition.fragment.text == assertion.fragment.text == "left < right"
    assert _halt_occurrence(condition) != _halt_occurrence(assertion)
