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


def _family_halts(outcome, comparisons, owners: tuple[str, str]) -> None:
    """Each leg's undecided dispatch is its own two-faced operation (#7585):
    one undetermined halt per leg, owned by that leg's operator, keyed on that
    leg's occurrence, under the complement of that leg's own
    ``python:compare.completes``.  No leg lends its halt or its occurrence to
    the other, and there is no second spelling of the halt's condition (the
    per-family ``python.<op>_dispatch_raises`` atoms are deleted)."""
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.occurrence import occurrence_key

    assert isinstance(outcome, ExitSet)
    halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
    assert len(halted) == 2
    by_owner = {exit_.effect.producer_node_owner: exit_ for exit_ in halted}
    assert set(by_owner) == set(owners)
    for owner, compare in zip(owners, comparisons, strict=True):
        halt = by_owner[owner]
        site = compare.sugar().site
        assert isinstance(halt.effect, UndeterminedRaiseEffect)
        assert halt.effect.exception_name is None
        assert halt.effect.occurrence_id == occurrence_key(site)
        assert halt.effect.blame == str(site)
        names = _atom_names(halt.guard)
        assert "python:compare.completes" in names
        assert not [name for name in names if name.endswith("dispatch_raises")]
    first, second = (by_owner[owner] for owner in owners)
    assert first.effect.occurrence_id != second.effect.occurrence_id
    # The second leg runs only past the first: its halt holds the first leg's
    # completion as well as its own complement, so the two guards differ.
    assert first.guard != second.guard


def test_symbolic_mixed_boolop_retains_each_family_law_and_occurrence() -> None:
    outcome, comparisons = _expression("a < b and c in d")

    _family_halts(
        outcome, comparisons, ("UndecidedCompare:Lt", "UndecidedCompare:In")
    )


def test_swapping_families_swaps_laws_without_collapsing_occurrences() -> None:
    outcome, comparisons = _expression("a in b and c < d")

    _family_halts(
        outcome, comparisons, ("UndecidedCompare:In", "UndecidedCompare:Lt")
    )


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
    source_calls = "mixed(1, 2, None, 3)\n"
    (outcome,), comparisons = _caller_outcomes(source_calls)
    (call,) = _calls_of(source_calls)
    halted = _only_halted(outcome)

    # ``None in 3`` raises at the second leg, stamped with the call's frame:
    # the one locus spelling (``file:line:col``, #7808), never the fragment's
    # repr.
    assert halted.effect.exception_name == "TypeError"
    assert halted.effect.occurrence_id == _locus(comparisons[1], call)
    assert halted.effect.occurrence_id != _locus(comparisons[0], call)
    assert halted.state is not None
