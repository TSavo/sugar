"""Formal unary operators: ``-x``, ``+x``, ``~x``.

Law (same door as formal binary / unary_truth):

  - formal alone → undischarged ``NativeOperationExitCarrierV1``
  - authenticated discharge → Floor fold (TermValue arithmetic / invert)
  - missing actuals stay undischarged
  - open (non-formal) SymbolicValue still refuses inventing success vs TypeError
  - ground production folds without a carrier
  - ``not x`` remains the separate ``unary_truth`` path (already enrolled)

No second dispatch table; projectors call Floor free methods explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
    production_native_operation_operators,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet
from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef, UnaryOp
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str = "unary_formal.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper(source: str):
    tree = _tree(source, "helper.py")
    function = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    return function, function.sugar().desugar(None)


@dataclass(frozen=True)
class _FloorSugar(Sugar):
    value: object

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)

    @classmethod
    def witnesses(cls):
        return ()


def _site_from(source: str = "def f(x):\n    return -x\n"):
    tree = _tree(source)
    function = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    unary = next(n for n in function.walk() if isinstance(n, UnaryOp))
    return unary.fragment


# ---------------------------------------------------------------------------
# Construction / production ground fold
# ---------------------------------------------------------------------------


def test_unary_op_sugar_constructs_for_usub() -> None:
    tree = _tree("def f(x):\n    return -x\n")
    function = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    unary = next(n for n in function.walk() if isinstance(n, UnaryOp))
    sugar = unary.sugar()
    assert isinstance(sugar, UnaryOpSugar)
    assert sugar.op_kind == "USub"


def test_ground_neg_plus_invert_fold() -> None:
    site = _site_from()
    assert (
        UnaryOpSugar("USub", _FloorSugar(TermValue(3)), site).desugar(None).value
        == TermValue(-3)
    )
    assert (
        UnaryOpSugar("UAdd", _FloorSugar(TermValue(3)), site).desugar(None).value
        == TermValue(3)
    )
    assert (
        UnaryOpSugar("Invert", _FloorSugar(TermValue(5)), site).desugar(None).value
        == TermValue(~5)
    )


def test_discrimination_neg_is_not_identity() -> None:
    site = _site_from()
    out = UnaryOpSugar("USub", _FloorSugar(TermValue(3)), site).desugar(None)
    assert out.value == TermValue(-3)
    with pytest.raises(AssertionError):
        assert out.value == TermValue(3)


# ---------------------------------------------------------------------------
# Formal undischarged carriers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source,operator",
    [
        ("def helper(x):\n    return -x\n", "unary_minus"),
        ("def helper(x):\n    return +x\n", "unary_plus"),
        ("def helper(x):\n    return ~x\n", "bitwise_invert"),
    ],
)
def test_helper_alone_is_undischarged_unary_carrier(source: str, operator: str) -> None:
    _, pending = _helper(source)
    assert isinstance(pending, NativeOperationExitCarrierV1), type(pending)
    assert pending.demand.operator == operator
    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge({})


def test_discrimination_helper_alone_is_not_completed() -> None:
    _, pending = _helper("def helper(x):\n    return -x\n")
    with pytest.raises(AssertionError):
        assert isinstance(pending, Complete)


def test_not_formal_stays_unary_truth_not_unary_minus() -> None:
    """``not x`` is truth-then-negate; must not steal the arithmetic unary door."""
    _, pending = _helper("def helper(x):\n    return not x\n")
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "unary_truth"
    with pytest.raises(AssertionError):
        assert pending.demand.operator == "unary_minus"


# ---------------------------------------------------------------------------
# Authenticated discharge
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source,operator,actual,expected",
    [
        ("def helper(x):\n    return -x\n", "unary_minus", TermValue(3), TermValue(-3)),
        ("def helper(x):\n    return +x\n", "unary_plus", TermValue(3), TermValue(3)),
        (
            "def helper(x):\n    return ~x\n",
            "bitwise_invert",
            TermValue(5),
            TermValue(~5),
        ),
    ],
)
def test_authenticated_discharge_folds_unary(
    source: str, operator: str, actual, expected
) -> None:
    function, pending = _helper(source)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == operator
    coords = {
        c.declared_name: c.coordinate_cid
        for c in function.sugar().formal_coordinates
    }
    exits = pending.discharge({coords["x"]: actual})
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    record = exits.exits[0].value.record
    rets = [s for s in record.statements if isinstance(s, ReturnValue)]
    assert rets and rets[-1].value == expected


def test_discrimination_discharged_neg_is_not_prior_value() -> None:
    function, pending = _helper("def helper(x):\n    return -x\n")
    coords = {
        c.declared_name: c.coordinate_cid
        for c in function.sugar().formal_coordinates
    }
    exits = pending.discharge({coords["x"]: TermValue(3)})
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    ret = next(
        s
        for s in exits.exits[0].value.record.statements
        if isinstance(s, ReturnValue)
    )
    assert ret.value == TermValue(-3)
    with pytest.raises(AssertionError):
        assert ret.value == TermValue(3)


# ---------------------------------------------------------------------------
# Open symbol still refuses inventing success
# ---------------------------------------------------------------------------


def test_open_symbolic_unary_still_refuses() -> None:
    """Non-formal SymbolicValue must not invent py.neg / identity completion."""
    site = _site_from()
    open_sym = SymbolicValue(make_var("xs"))
    with pytest.raises(SugarNotWritten, match="unary_operation_exception_floor"):
        UnaryOpSugar("USub", _FloorSugar(open_sym), site).desugar(None)


def test_discrimination_open_symbol_is_not_silent_neg_coordinate() -> None:
    site = _site_from()
    open_sym = SymbolicValue(make_var("xs"))
    with pytest.raises(SugarNotWritten):
        out = UnaryOpSugar("USub", _FloorSugar(open_sym), site).desugar(None)
        # Lying claim: open symbol completed as a success coordinate.
        assert isinstance(out, Complete)


# ---------------------------------------------------------------------------
# Projector / production equality tooth
# ---------------------------------------------------------------------------


def test_unary_projectors_enrolled_and_equal_production() -> None:
    for name in ("unary_minus", "unary_plus", "bitwise_invert"):
        assert name in _NATIVE_OPERATION_PROJECTORS
    production = production_native_operation_operators()
    assert production == frozenset(_NATIVE_OPERATION_PROJECTORS)
    for name in ("unary_minus", "unary_plus", "bitwise_invert"):
        assert name in production


def test_unary_projectors_call_floor_methods_not_binary_standin() -> None:
    """Discharge projectors are unary Floor methods — arity 1 + site."""
    import inspect

    for name in ("unary_minus", "unary_plus", "bitwise_invert"):
        projector = _NATIVE_OPERATION_PROJECTORS[name]
        # site is last; one operand.
        assert len(inspect.signature(projector).parameters) == 2
    assert _NATIVE_OPERATION_PROJECTORS["unary_minus"](TermValue(4), "s").value == (
        TermValue(-4)
    )
    with pytest.raises(AssertionError):
        # Lying: unary_minus is not add-shaped (2 operands + site).
        assert len(inspect.signature(_NATIVE_OPERATION_PROJECTORS["unary_minus"]).parameters) == 3
