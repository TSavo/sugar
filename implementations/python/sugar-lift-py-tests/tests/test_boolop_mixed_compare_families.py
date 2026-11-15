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


def test_a_call_of_mixed_is_its_coordinate_and_edge() -> None:
    """#7757 step 5 (#8705, "Edge, join at prove"): each call of ``mixed`` is
    its coordinate and edge, the one unanswered call (completes under its
    ``python:unknown_callee_call.completes`` atom, halts under the complement
    naming nothing), never ``mixed``'s body applied to the actuals.  Which leg
    raises for which actuals is stated by ``mixed``'s contract over its
    formals (each leg's own two-faced halt, above) and decided at prove.

    Replaces ``test_first_leg_halt_blocks_toxic_and_safe_membership_with_
    exact_state`` and ``test_truthful_first_leg_routes_membership_halt_to_
    second_occurrence_and_state``, which read each leg's halt and the callee's
    state off the body applied at the call: the mechanism #8705 deleted.  The
    same leg facts over literals are the tests above."""
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect

    tree = _caller_tree(
        "mixed(None, 1, None, 3)\n" "mixed(None, 1, 1, [1])\n" "mixed(1, 2, None, 3)\n"
    )
    comparisons = tuple(node for node in tree.nodes() if isinstance(node, Compare))
    assert len(comparisons) == 2
    legs = {
        AuthenticatedRaiseLocus.of(compare.sugar().site).value
        for compare in comparisons
    }
    outcomes = tuple(
        node.sugar().desugar(None) for node in tree.nodes() if isinstance(node, Call)
    )
    assert len(outcomes) == 3
    for outcome in outcomes:
        assert isinstance(outcome, ExitSet)
        assert len(outcome.exits) == 2
        (halted,) = outcome.halts()
        assert isinstance(halted, Halted)
        assert type(halted.effect) is UndeterminedRaiseEffect
        assert halted.effect.exception_name is None
        raised_at = str(halted.effect.occurrence_id)
        assert not any(raised_at.startswith(leg) for leg in legs)
