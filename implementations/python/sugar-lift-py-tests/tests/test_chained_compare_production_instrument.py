"""Production instrument for chained Compare control and per-leg laws."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus
from sugar_lift_py_tests.ir import and_, atomic, ctor, make_var, not_, str_const
from sugar_lift_py_tests.occurrence import occurrence_key
from sugar_lift_py_tests.outcome import ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_source_tree.nodes import Compare
from sugar_source_tree.tree import SourceFile


def _helper(expression: str) -> str:
    return (
        "def chain():\n" f"    if {expression}:\n" "        return 1\n" "    return 0\n"
    )


def _tree(calls: str = "", helper: str = _helper("1 < 2 < 3")) -> SourceFile:
    source = f"{helper}\n{calls}"
    return SourceFile(
        (source, "chained-compare-production.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _pair_sites(tree: SourceFile):
    compare = next(node for node in tree.nodes() if isinstance(node, Compare))
    return tuple(value.site for value in compare.sugar().values)


def _occurrence(site) -> str:
    return str(site)


def _undecided_occurrence(site) -> str:
    """An undecided comparison's halt names its occurrence by the site's
    coordinate CID (``comparison_op_sugar.undecided_dispatch_faces``)."""
    return occurrence_key(site, ())


def _only(outcome, kind):
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    exit_ = outcome.exits[0]
    assert isinstance(exit_, kind)
    return exit_


def _type_error_identity():
    from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

    return TemporalContext.empty().value_for("TypeError").exception_type_identity()


def test_successful_chain_selects_the_true_body() -> None:
    tree = _tree()
    outcome = (
        next(node for node in tree.nodes() if isinstance(node, Compare))
        .sugar()
        .desugar(None)
    )
    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), TrueBoolLiteralSugar)


def test_false_first_leg_selects_false_body_and_emits_no_second_occurrence() -> None:
    tree = _tree("chain()\n", _helper("2 < 1 < None"))
    first_site, second_site = _pair_sites(tree)
    outcome = (
        next(node for node in tree.nodes() if isinstance(node, Compare))
        .sugar()
        .desugar(None)
    )

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), FalseBoolLiteralSugar)
    assert _occurrence(outcome.completed_value().site) == _occurrence(first_site)
    assert _occurrence(outcome.completed_value().site) != _occurrence(second_site)
    assert _occurrence(first_site) != _occurrence(second_site)


@pytest.mark.parametrize(
    ("expression", "leg"),
    (("None < 2 < 3", 0), ("1 < 2 < None", 1)),
    ids=("first-leg", "second-leg"),
)
def test_named_type_error_keeps_the_evaluated_leg_occurrence(
    expression: str, leg: int
) -> None:
    """The chain reduced where it stands, in ``chain``'s body (the reduction
    ``chain``'s contract states).  Before #8705 this read the halt off
    ``chain()``, the body applied at the call; a same-file call is now its
    coordinate and edge (#7757 step 5, "Edge, join at prove"), so the call
    names nothing and the leg's ``TypeError`` is the callee's own halt,
    joined at prove."""
    tree = _tree("", _helper(expression))
    sites = _pair_sites(tree)
    outcome = (
        next(node for node in tree.nodes() if isinstance(node, Compare))
        .sugar()
        .desugar(None)
    )

    halted = _only(outcome, Halted)
    assert halted.effect.exception_type_coordinate == _type_error_identity()
    assert halted.effect.occurrence_id == AuthenticatedRaiseLocus.of(sites[leg]).value
    assert halted.effect.occurrence_id != (
        AuthenticatedRaiseLocus.of(sites[1 - leg]).value
    )


def test_undecidable_ordering_legs_keep_exact_guards_and_occurrences() -> None:
    tree = _tree("", "def f(a, b, c):\n    return a < b < c\n")
    compare = next(node for node in tree.nodes() if isinstance(node, Compare))
    sugar = compare.sugar()
    outcome = sugar.desugar(None)
    assert isinstance(outcome, ExitSet)

    # Each undecided leg is the one two-faced outcome: it completes under its
    # own site-keyed ``python:compare.completes`` atom and halts, with an
    # undetermined raise, under that atom's complement
    # (``comparison_op_sugar.undecided_dispatch_faces``). The atom names the
    # leg's operation: its operator, its two operand terms, then its site key
    # (#7766). The second leg runs only where the first completed and was true.
    def completes(site, left, right):
        return atomic(
            "python:compare.completes",
            [
                ctor(
                    "python:compare",
                    (
                        str_const("Lt"),
                        left,
                        right,
                        str_const(_undecided_occurrence(site)),
                    ),
                )
            ],
        )

    a, b, c = make_var("a"), make_var("b"), make_var("c")
    first_site, second_site = (value.site for value in sugar.values)
    first_completes = completes(first_site, a, b)
    second_completes = completes(second_site, b, c)
    # The first leg's value, keyed per evaluation like its completes atom
    # (#7757 NEW-1).
    first_true = atomic(
        "python:compare_result",
        [str_const("Lt"), a, b, str_const(_undecided_occurrence(first_site))],
    )
    halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
    assert {exit_.guard for exit_ in halted} == {
        not_(first_completes),
        and_([first_completes, and_([first_true, not_(second_completes)])]),
    }
    assert {exit_.effect.occurrence_id for exit_ in halted} == {
        _undecided_occurrence(first_site),
        _undecided_occurrence(second_site),
    }
    assert {exit_.effect.producer_node_owner for exit_ in halted} == {
        "UndecidedCompare:Lt"
    }


@pytest.mark.parametrize(
    ("expression", "raising_legs", "identity_first"),
    (
        (
            "a < b == c",
            {"UndecidedCompare:Lt", "UndecidedCompare:Eq"},
            False,
        ),
        ("a is b < c", {"UndecidedCompare:Lt"}, True),
        (
            "a in b < c",
            {"UndecidedCompare:In", "UndecidedCompare:Lt"},
            False,
        ),
    ),
    ids=("ordering-equality", "identity-ordering", "membership-ordering"),
)
def test_mixed_chain_legs_retain_separate_exception_laws(
    expression: str, raising_legs: set[str], identity_first: bool
) -> None:
    """Each leg whose operands' types are undecided may raise by its own
    law: the rich method (``__lt__`` / ``__eq__`` / ``__contains__``) Python
    selects was not looked at, so the leg completes under
    ``python:compare.completes`` or halts at its own site with the undecided
    member (``UndecidedCompare:<op>``).  ``is`` runs no user code and never
    halts."""
    tree = _tree("", f"def f(a, b, c):\n    return {expression}\n")
    compare = next(node for node in tree.nodes() if isinstance(node, Compare))
    sugar = compare.sugar()
    outcome = sugar.desugar(None)
    assert isinstance(outcome, ExitSet)

    halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))

    assert {exit_.effect.producer_node_owner for exit_ in halted} == raising_legs
    occurrences = {exit_.effect.occurrence_id for exit_ in halted}
    if identity_first:
        assert occurrences == {_undecided_occurrence(sugar.values[1].site)}
    else:
        assert occurrences == {
            _undecided_occurrence(value.site) for value in sugar.values
        }


def test_identity_first_leg_is_not_a_native_operation_carrier() -> None:
    tree = _tree("", "def f(a, b, c):\n    return a is b < c\n")
    compare = next(node for node in tree.nodes() if isinstance(node, Compare))
    outcome = compare.sugar().values[0].desugar(None)

    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    assert isinstance(outcome, ExitSet)
