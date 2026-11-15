"""A BoolOp composes comparison families without lending laws between them."""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus
from sugar_lift_py_tests.occurrence import call_frame_path
from sugar_lift_py_tests.outcome import ExitSet, Halted
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import BoolOp, Call, Compare
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.effect import RaiseEffect


def _expression(source_expression: str):
    source = f"def mixed(a, b, c, d):\n    return {source_expression}\n"
    tree = SourceFile(
        (source, "boolop-mixed-families.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    boolop = next(node for node in tree.nodes() if isinstance(node, BoolOp))
    comparisons = tuple(node for node in tree.nodes() if isinstance(node, Compare))
    assert len(comparisons) == 2
    return boolop.sugar().desugar(None), comparisons


def _raise_occurrence(outcome) -> str:
    assert isinstance(outcome, ExitSet)
    halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
    assert len(halted) == 1
    if len(outcome.exits) == 1:
        # A sole halt is the raise itself.
        assert isinstance(halted[0].effect, RaiseEffect)
    assert (
        isinstance(halted[0].effect.occurrence_id, str)
        and ":" in halted[0].effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted[0].effect.occurrence_id!r}"
    )
    return halted[0].effect.occurrence_id


def test_false_ordering_short_circuits_membership_and_returns_first_operand() -> None:
    outcome, comparisons = _expression("2 < 1 and None in 3")

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), FalseBoolLiteralSugar)
    assert str(outcome.completed_value().site) == str(comparisons[0].sugar().site)
    assert str(outcome.completed_value().site) != str(comparisons[1].sugar().site)


def _locus(compare: Compare, call: Call | None = None) -> str:
    """The raise locus of a ``TypeError`` raised at ``compare``: its
    ``file:line:col`` (``AuthenticatedRaiseLocus.of``, never the fragment's
    repr, #7808), stamped with the call frame it was raised in when it crossed
    ``call`` (``call_site_value.call_owned``)."""
    locus = AuthenticatedRaiseLocus.of(compare.sugar().site).value
    if call is None:
        return locus
    return f"{locus}@{'/'.join(call_frame_path(call.fragment, ()))}"


def test_truthful_ordering_evaluates_membership_exception_at_second_site() -> None:
    outcome, comparisons = _expression("1 < 2 and None in 3")

    assert _raise_occurrence(outcome) == _locus(comparisons[1])
    assert _raise_occurrence(outcome) != _locus(comparisons[0])


def test_ordering_exception_bypasses_membership_and_keeps_first_site() -> None:
    outcome, comparisons = _expression("None < 1 and 1 in [1]")

    assert _raise_occurrence(outcome) == _locus(comparisons[0])
    assert _raise_occurrence(outcome) != _locus(comparisons[1])


def _atom_names(formula) -> set[str]:
    name = getattr(formula, "name", None)
    found = {name} if isinstance(name, str) else set()
    for operand in getattr(formula, "operands", ()):
        found.update(_atom_names(operand))
    return found


def test_symbolic_mixed_boolop_retains_each_family_law_and_occurrence() -> None:
    outcome, comparisons = _expression("a < b and c in d")

    assert isinstance(outcome, ExitSet)
    halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
    assert len(halted) == 2
    assert {
        name
        for exit_ in halted
        for name in _atom_names(exit_.guard)
        if name.endswith("dispatch_raises")
    } == {"python.lt_dispatch_raises", "python.contains_dispatch_raises"}
    assert {exit_.effect.occurrence_id for exit_ in halted} == {
        str(compare.sugar().site) for compare in comparisons
    }


def test_swapping_families_swaps_laws_without_collapsing_occurrences() -> None:
    outcome, comparisons = _expression("a in b and c < d")

    assert isinstance(outcome, ExitSet)
    halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
    assert len(halted) == 2
    assert {
        name
        for exit_ in halted
        for name in _atom_names(exit_.guard)
        if name.endswith("dispatch_raises")
    } == {"python.contains_dispatch_raises", "python.lt_dispatch_raises"}
    assert {exit_.effect.occurrence_id for exit_ in halted} == {
        str(compare.sugar().site) for compare in comparisons
    }


def _caller_tree(calls: str) -> SourceFile:
    source = "def mixed(a, b, c, d):\n" "    return a < b and c in d\n" f"\n{calls}"
    return SourceFile(
        (source, "boolop-mixed-caller.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _calls_of(calls: str) -> tuple[Call, ...]:
    return tuple(node for node in _caller_tree(calls).nodes() if isinstance(node, Call))


def _caller_outcomes(calls: str):
    tree = _caller_tree(calls)
    comparisons = tuple(node for node in tree.nodes() if isinstance(node, Compare))
    outcomes = tuple(
        node.sugar().desugar(None) for node in tree.nodes() if isinstance(node, Call)
    )
    assert len(comparisons) == 2
    return outcomes, comparisons


def _only_halted(outcome) -> Halted:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    return halted


def _formal_occurrence(compare: Compare) -> str:
    return str(compare.sugar().site)


def test_first_leg_halt_blocks_toxic_and_safe_membership_with_exact_state() -> None:
    source_calls = "mixed(None, 1, None, 3)\n" "mixed(None, 1, 1, [1])\n"
    (toxic, safe), comparisons = _caller_outcomes(source_calls)
    toxic_call, safe_call = _calls_of(source_calls)
    toxic_halt = _only_halted(toxic)
    safe_halt = _only_halted(safe)

    # Each call raises at the first leg, stamped with its own call frame.
    assert toxic_halt.effect.occurrence_id == _locus(comparisons[0], toxic_call)
    assert safe_halt.effect.occurrence_id == _locus(comparisons[0], safe_call)
    assert toxic_halt.effect.occurrence_id != _locus(comparisons[1], toxic_call)
    assert toxic_halt.state is not None
    assert safe_halt.state is not None
    assert toxic_halt.state == safe_halt.state


def test_truthful_first_leg_routes_membership_halt_to_second_occurrence_and_state() -> (
    None
):
    (outcome,), comparisons = _caller_outcomes("mixed(1, 2, None, 3)\n")
    halted = _only_halted(outcome)

    assert halted.effect.occurrence_id == _formal_occurrence(comparisons[1])
    assert halted.effect.occurrence_id != _formal_occurrence(comparisons[0])
    assert halted.state is not None
