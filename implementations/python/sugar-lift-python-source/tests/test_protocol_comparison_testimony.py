"""A comparison consumer must retain native Floor outcomes, not invent exits."""

import pytest

from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.floor import (
    PredicateValue,
    StringValue,
    SymbolicValue,
)
from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.outcome import ExitSet, Halted
from sugar_lift_py_tests.sugar.comparison_op_sugar import (
    publish_undecided_comparison_edges,
)
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import RaiseEffect


def _comparison(op):
    operator = {"Eq": "==", "NotEq": "!=", "In": "in", "NotIn": "not in"}[op]
    source = f'left {operator} "needle"\n'
    tree = SourceFile(
        (source, "native-comparison.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    return next(node for node in tree.nodes() if node.kind == "Compare").fragment


@pytest.mark.parametrize("op", ["Eq", "NotEq", "In", "NotIn"])
@pytest.mark.parametrize("exception", ["ValueError", "LookupError"])
@pytest.mark.parametrize("shape", ["raise-value", "exit-set"])
def test_native_comparison_exception_testimony_survives_undecided_operands(
    op, exception, shape
):
    site = _comparison(op)
    left, right = SymbolicValue(make_var("left")), StringValue("needle")
    native = ground_exceptional_exit(
        exception_name=exception, site=site, owner="NativeComparison"
    )
    assert native.halts() == native.exits
    (native_halt,) = native.halts()
    assert isinstance(native_halt.effect, RaiseEffect)
    # This seam receives an already-constructed outcome from the native Floor.
    # Operand undecidability must not erase its authenticated type/occurrence.
    effect = native_halt.effect
    if shape == "exit-set":
        state = object()
        guard = atomic("native.comparison.raises", ())
        native = ExitSet((Halted(guard, effect, state=state),))
    result = publish_undecided_comparison_edges(left, right, site, op, native)
    assert result is native
    if shape == "exit-set":
        assert result.exits[0].effect is effect
        assert result.exits[0].guard is guard
        assert result.exits[0].state is state
    else:
        (result_halt,) = result.halts()
        assert result_halt.effect is effect
    assert effect.exception_type_coordinate is not None
    assert effect.occurrence is not None
    assert effect.exception_name == exception


@pytest.mark.parametrize("op", ["Eq", "NotEq", "In", "NotIn"])
def test_undecided_comparison_predicate_is_not_native_completion_testimony(op):
    site = _comparison(op)
    left, right = SymbolicValue(make_var("left")), StringValue("needle")
    unproven = ExitSet.completed(
        PredicateValue(atomic("py.eq", (left.term, right.to_term(owner="right"))), site)
    )
    # The predicate alone is not testimony that dispatch completes: the
    # undecided ``__eq__``/``__contains__`` may raise anything.  It completes
    # only under ``python:compare.completes`` and halts undetermined (no
    # invented exception type) under the complement -- the #7585 two faces.
    result = publish_undecided_comparison_edges(left, right, site, op, unproven)
    assert isinstance(result, ExitSet)
    (completed,) = [face for face in result.exits if not isinstance(face, Halted)]
    (halted,) = [face for face in result.exits if isinstance(face, Halted)]
    assert completed.value is unproven.completed_value()
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
        def equals(self, other, site):
            return native

        def contains(self, other, site):
            return native

    left = NativeOperand(make_var("left"))
    right = NativeOperand(make_var("right"))
    result = comparison.sugar().apply_reduced(left, right)
    assert result is native
    assert result.halts() == result.exits
    (halt,) = result.halts()
    assert halt.effect.exception_name == "LookupError"
