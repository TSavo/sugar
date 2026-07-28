"""Formal unary operators: ``-x``, ``+x``, ``~x``.

Law (same door as formal binary / unary_truth):

  - formal alone → undischarged ``NativeOperationExitCarrierV1``
  - production caller (positional / keyword / default) → bind_actuals →
    carrier discharge → Completed fold
  - wrong-coordinate / missing actual → no fabricated completion
  - open (non-formal) SymbolicValue still refuses inventing success vs TypeError
  - ground production folds without a carrier
  - ``not x`` remains the separate ``unary_truth`` path (already enrolled)

Discharge is proved only through the production call binder — never by
manually building a coordinate dict and calling ``pending.discharge``.
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
from sugar_source_tree.nodes import Call, FunctionDef, UnaryOp
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


def _call_outcome(signature: str, body: str, actuals: str):
    """Production call: helper body + call site through call construction."""
    source = f"def helper({signature}):\n    {body}\n\nhelper({actuals})\n"
    tree = _tree(source, "unary_call.py")
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def _returned_value(outcome):
    """Completed production call → body return Floor value."""
    assert isinstance(outcome, ExitSet), type(outcome)
    assert len(outcome.exits) == 1
    face = outcome.exits[0]
    assert isinstance(face, Completed), type(face)
    value = face.value
    force = getattr(value, "force_floor", None)
    if callable(force):
        forced = force(None, owner="unary_formal_caller")
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.return_value import ReturnValue

        if isinstance(forced, BlockValue):
            returns = [s for s in forced.statements if isinstance(s, ReturnValue)]
            assert returns, forced.statements
            return returns[-1].value
        return forced
    record = getattr(value, "record", None)
    if record is not None:
        from sugar_lift_py_tests.floor.return_value import ReturnValue

        returns = [s for s in record.statements if isinstance(s, ReturnValue)]
        if returns:
            return returns[-1].value
    return value


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
# Formal undischarged carriers (helper alone — no caller)
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
# Production callers: call construction → bind_actuals → discharge → Completed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body,actuals,expected",
    [
        ("return -x", "3", TermValue(-3)),
        ("return +x", "3", TermValue(3)),
        ("return ~x", "5", TermValue(~5)),
    ],
)
def test_positional_caller_discharges_unary_through_production_binder(
    body: str, actuals: str, expected
) -> None:
    """Real SourceFile caller — not a hand-built coordinate discharge dict."""
    outcome = _call_outcome("x", body, actuals)
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    assert isinstance(outcome.exits[0], Completed)
    assert _returned_value(outcome) == expected


def test_keyword_caller_discharges_unary_neg() -> None:
    outcome = _call_outcome("x", "return -x", "x=4")
    assert isinstance(outcome.exits[0], Completed)
    assert _returned_value(outcome) == TermValue(-4)


def test_default_caller_discharges_unary_neg() -> None:
    outcome = _call_outcome("x=7", "return -x", "")
    assert isinstance(outcome.exits[0], Completed)
    assert _returned_value(outcome) == TermValue(-7)


def test_positional_keyword_and_default_callers_complete_same_neg_fold() -> None:
    """Binder twins: positional, keyword, and default all fold ``-x`` the same way."""
    positional = _call_outcome("x", "return -x", "3")
    keyword = _call_outcome("x", "return -x", "x=3")
    default = _call_outcome("x=3", "return -x", "")
    for outcome in (positional, keyword, default):
        assert isinstance(outcome, ExitSet)
        assert isinstance(outcome.exits[0], Completed)
        assert _returned_value(outcome) == TermValue(-3)


def test_discrimination_production_neg_is_not_prior_actual() -> None:
    outcome = _call_outcome("x", "return -x", "3")
    returned = _returned_value(outcome)
    assert returned == TermValue(-3)
    with pytest.raises(AssertionError):
        assert returned == TermValue(3)


# ---------------------------------------------------------------------------
# Wrong-coordinate / missing-actual: no fabricated completion
# ---------------------------------------------------------------------------


def test_wrong_coordinate_actual_cannot_discharge_pending_unary() -> None:
    """Swapped/wrong coordinate keys must not fabricate a Completed fold."""
    function, pending = _helper("def helper(x):\n    return -x\n")
    assert isinstance(pending, NativeOperationExitCarrierV1)
    (coord,) = function.formal_coordinates()
    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge({f"wrong:{coord.coordinate_cid}": TermValue(3)})


def test_missing_actual_does_not_fabricate_completed_neg() -> None:
    """Empty discharge stays undischarged — never Completed TermValue(0) etc."""
    _, pending = _helper("def helper(x):\n    return -x\n")
    assert isinstance(pending, NativeOperationExitCarrierV1)
    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        fabricated = pending.discharge({})
        # If discharge ever went soft, a lying complete would look like this:
        assert isinstance(fabricated, ExitSet) and isinstance(
            fabricated.exits[0], Completed
        )


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
        assert (
            len(inspect.signature(_NATIVE_OPERATION_PROJECTORS["unary_minus"]).parameters)
            == 3
        )
