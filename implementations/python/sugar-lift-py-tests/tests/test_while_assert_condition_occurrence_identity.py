"""Control conditions own one source occurrence, distinct from body sites."""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.occurrence import occurrence_key
from sugar_lift_py_tests.outcome import ExitSet, Halted
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
    assert isinstance(halted[0].effect.occurrence_id, str), halted[0].effect
    return halted[0].effect.occurrence_id


def _undecided_occurrence(compare: Compare) -> str:
    """The occurrence an undecided comparison's halt names: its site's
    coordinate key (``comparison_op_sugar.undecided_dispatch_faces``,
    ``occurrence_key``), never the fragment's repr, which is a print format
    and not an address (#7808)."""
    return occurrence_key(compare.sugar().site, ())


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

    expected = _undecided_occurrence(condition)
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

    expected = _undecided_occurrence(assertion)
    assert first == expected
    assert repeated == expected


def test_assert_condition_halt_keeps_its_condition_occurrence() -> None:
    tree = _tree("def check():\n    assert None < 1\n")
    assertion = next(node for node in tree.nodes() if isinstance(node, Assert))
    assert isinstance(assertion.test, Compare)
    condition_site = assertion.test.sugar().site
    outcome = assertion.sugar().desugar(None)

    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.occurrence_id == (
        f"{condition_site.filename}:{condition_site.line}:{condition_site.col}"
    )


def test_identical_condition_and_body_operands_do_not_collapse_occurrences() -> None:
    condition, assertion = _comparisons()

    assert condition.fragment.text == assertion.fragment.text == "left < right"
    assert _halt_occurrence(condition) != _halt_occurrence(assertion)
