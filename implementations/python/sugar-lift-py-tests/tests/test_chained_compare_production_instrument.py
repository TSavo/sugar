"""Production instrument for chained Compare control and per-leg laws."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.ir import and_, atomic, make_var, not_
from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_source_tree.nodes import Call, Compare
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


def _calls(tree: SourceFile):
    return tuple(
        node.sugar().desugar(None) for node in tree.nodes() if isinstance(node, Call)
    )


def _pair_sites(tree: SourceFile):
    compare = next(node for node in tree.nodes() if isinstance(node, Compare))
    return tuple(value.site for value in compare.sugar().values)


def _occurrence(site) -> str:
    return str(site)


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
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)


def test_false_first_leg_selects_false_body_and_emits_no_second_occurrence() -> None:
    tree = _tree("chain()\n", _helper("2 < 1 < None"))
    first_site, second_site = _pair_sites(tree)
    outcome = (
        next(node for node in tree.nodes() if isinstance(node, Compare))
        .sugar()
        .desugar(None)
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, FalseBoolLiteralSugar)
    assert _occurrence(outcome.value.site) == _occurrence(first_site)
    assert _occurrence(outcome.value.site) != _occurrence(second_site)
    assert _occurrence(first_site) != _occurrence(second_site)


@pytest.mark.parametrize(
    ("expression", "leg"),
    (("None < 2 < 3", 0), ("1 < 2 < None", 1)),
    ids=("first-leg", "second-leg"),
)
def test_named_type_error_keeps_the_evaluated_leg_occurrence(
    expression: str, leg: int
) -> None:
    tree = _tree("chain()\n", _helper(expression))
    sites = _pair_sites(tree)
    (outcome,) = _calls(tree)

    halted = _only(outcome, Halted)
    assert halted.effect.exception_type_coordinate == _type_error_identity()
    assert halted.effect.occurrence_id == _occurrence(sites[leg])
    assert halted.effect.occurrence_id != _occurrence(sites[1 - leg])


def test_undecidable_ordering_legs_keep_exact_guards_and_occurrences() -> None:
    tree = _tree("", "def f(a, b, c):\n    return a < b < c\n")
    compare = next(node for node in tree.nodes() if isinstance(node, Compare))
    sugar = compare.sugar()
    outcome = sugar.desugar(None)
    assert isinstance(outcome, ExitSet)

    a, b, c = make_var("a"), make_var("b"), make_var("c")
    first_raises = atomic("python.lt_dispatch_raises", [a, b])
    first_true = atomic("py.lt", [a, b])
    second_raises = atomic("python.lt_dispatch_raises", [b, c])
    halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
    assert {exit_.guard for exit_ in halted} == {
        first_raises,
        and_([not_(first_raises), and_([first_true, second_raises])]),
    }
    assert {exit_.effect.occurrence_id for exit_ in halted} == {
        _occurrence(value.site) for value in sugar.values
    }


@pytest.mark.parametrize(
    ("expression", "raise_atoms", "identity_first"),
    (
        (
            "a < b == c",
            {"python.lt_dispatch_raises", "python.eq_dispatch_raises"},
            False,
        ),
        ("a is b < c", {"python.lt_dispatch_raises"}, True),
        (
            "a in b < c",
            {"python.contains_dispatch_raises", "python.lt_dispatch_raises"},
            False,
        ),
    ),
    ids=("ordering-equality", "identity-ordering", "membership-ordering"),
)
def test_mixed_chain_legs_retain_separate_exception_laws(
    expression: str, raise_atoms: set[str], identity_first: bool
) -> None:
    tree = _tree("", f"def f(a, b, c):\n    return {expression}\n")
    compare = next(node for node in tree.nodes() if isinstance(node, Compare))
    sugar = compare.sugar()
    outcome = sugar.desugar(None)
    assert isinstance(outcome, ExitSet)

    halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))

    def atoms(formula):
        name = getattr(formula, "name", None)
        if isinstance(name, str):
            yield formula
        for operand in getattr(formula, "operands", ()):
            yield from atoms(operand)

    observed = {
        atom.name
        for exit_ in halted
        for atom in atoms(exit_.guard)
        if getattr(atom, "name", "").endswith("dispatch_raises")
    }
    assert observed == raise_atoms
    occurrences = {exit_.effect.occurrence_id for exit_ in halted}
    if identity_first:
        assert occurrences == {_occurrence(sugar.values[1].site)}
    else:
        assert occurrences == {_occurrence(value.site) for value in sugar.values}


def test_identity_first_leg_is_not_a_native_operation_carrier() -> None:
    tree = _tree("", "def f(a, b, c):\n    return a is b < c\n")
    compare = next(node for node in tree.nodes() if isinstance(node, Compare))
    outcome = compare.sugar().values[0].desugar(None)

    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    assert isinstance(outcome, (Complete, ExitSet))
