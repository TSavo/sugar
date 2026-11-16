"""A comparison consumer must retain native Floor outcomes, not invent exits.

Every test reaches the consumer the way a lifted file does: the ``Compare``
node's own sugar applied to its reduced operands (``apply_reduced``), which
routes ``==`` / ``!=`` through the equality law and ``in`` / ``not in``
through the membership law.
"""

import pytest

from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.floor import (
    PredicateValue,
    SymbolicValue,
)
from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.outcome import ExitSet, Halted
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import RaiseEffect


def _comparison(operator):
    source = f"left {operator} right\n"
    tree = SourceFile(
        (source, "native-comparison.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    return next(node for node in tree.nodes() if node.kind == "Compare")


def _operands(outcome):
    """Two undecided operands whose floor answers ``outcome`` for both the
    equality (``left.equals``) and the membership (``right.contains``) law."""

    class Operand(SymbolicValue):
        def equals(self, other, site, ctx):
            return outcome

        def contains(self, other, site):
            return outcome

    return Operand(make_var("left")), Operand(make_var("right"))


def _retains(result, native):
    """``result`` is ``native``'s halts, each as the floor answered it.

    ``!=``, ``in`` and ``not in`` reach the law through the one composition
    (``ExitSet.and_then`` over each operand's receiver, then the negated
    truth), which rebuilds the set: the halts bypass every tail and keep
    their effect and state objects, and the guard is the same formula.  No
    exit is invented, negated or retyped."""
    assert isinstance(result, ExitSet)
    assert result.halts() == result.exits
    assert len(result.exits) == len(native.exits)
    for kept, answered in zip(result.exits, native.exits):
        assert kept.effect is answered.effect
        assert kept.state is answered.state
        assert kept.guard == answered.guard


@pytest.mark.parametrize("operator", ["==", "!=", "in", "not in"])
@pytest.mark.parametrize("exception", ["ValueError", "LookupError"])
@pytest.mark.parametrize("shape", ["raise-value", "exit-set"])
def test_native_comparison_exception_testimony_survives_undecided_operands(
    operator, exception, shape
):
    comparison = _comparison(operator)
    site = comparison.fragment
    native = ground_exceptional_exit(
        exception_name=exception, site=site, owner="NativeComparison"
    )
    assert native.halts() == native.exits
    (native_halt,) = native.halts()
    assert isinstance(native_halt.effect, RaiseEffect)
    # The floor hands the consumer an already-constructed outcome.  Operand
    # undecidability must not erase its authenticated type/occurrence.
    effect = native_halt.effect
    if shape == "exit-set":
        from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

        state = _ReducedBlock((), True, ())
        guard = atomic("native.comparison.raises", ())
        native = ExitSet((Halted(guard, effect, state=state),))
    left, right = _operands(native)
    result = comparison.sugar().apply_reduced(left, right)
    _retains(result, native)
    if shape == "exit-set":
        assert result.exits[0].effect is effect
        assert result.exits[0].guard == guard
        assert result.exits[0].state is state
    else:
        (result_halt,) = result.halts()
        assert result_halt.effect is effect
    assert effect.exception_type_coordinate is not None
    assert effect.occurrence is not None
    assert effect.exception_name == exception


@pytest.mark.parametrize(("operator", "op"), [("==", "Eq"), ("in", "In")])
def test_undecided_comparison_predicate_is_not_native_completion_testimony(
    operator, op
):
    comparison = _comparison(operator)
    site = comparison.fragment
    left = SymbolicValue(make_var("left"))
    right = SymbolicValue(make_var("right"))
    # Two operands whose types are undecided: the undecided
    # ``__eq__``/``__contains__`` may raise anything.  The floor answers
    # that itself (``equality_atom.answered_equality``,
    # ``FloorValue.undecided_contains``): it completes only under
    # ``python:compare.completes`` and halts undetermined (no invented
    # exception type) under the complement -- the #7585 two faces, never a
    # bare predicate a later pass patches (#7757).
    result = comparison.sugar().apply_reduced(left, right)
    assert isinstance(result, ExitSet)
    (completed,) = [face for face in result.exits if not isinstance(face, Halted)]
    (halted,) = [face for face in result.exits if isinstance(face, Halted)]
    # Keyed per evaluation at the halt's key (#7757 NEW-1): the truth of the
    # comparison's value, ``python:truth_result(python:compare_result(
    # "<op>", left, right, <key>), <key>)``, operands in the atom's order
    # (``left in right`` is item then container).
    assert type(completed.value) is PredicateValue
    assert completed.value.site is site
    assert completed.value.formula.name == "python:truth_result"
    compared = completed.value.formula.args[0]
    assert compared.name == "python:compare_result"
    assert compared.args[0].value == op
    assert compared.args[1:-1] == (left.term, right.term)
    assert compared.args[-1].value == halted.effect.occurrence
    assert completed.value.formula.args[-1].value == halted.effect.occurrence
    assert completed.guard.name == "python:compare.completes"
    assert isinstance(halted.effect, UndeterminedRaiseEffect)
    assert halted.effect.exception_name is None
    assert halted.effect.producer_node_owner == f"UndecidedCompare:{op}"


@pytest.mark.parametrize("operator", ["==", "!=", "in", "not in"])
def test_comparison_sugar_preserves_native_raise_without_negating_or_retyping(operator):
    source = f"left {operator} right\n"
    tree = SourceFile(
        (source, "comparison-consumer.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    comparison = next(node for node in tree.nodes() if node.kind == "Compare")
    native = ground_exceptional_exit(
        exception_name="LookupError", site=comparison.fragment, owner="NativeComparison"
    )

    class NativeOperand(SymbolicValue):
        def equals(self, other, site, ctx):
            return native

        def contains(self, other, site):
            return native

    left = NativeOperand(make_var("left"))
    right = NativeOperand(make_var("right"))
    result = comparison.sugar().apply_reduced(left, right)
    _retains(result, native)
    (halt,) = result.halts()
    assert halt.effect.exception_name == "LookupError"
