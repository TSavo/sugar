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
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
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


def _call_edge(signature: str, body: str, actuals: str):
    """Production call: ``helper({actuals})`` in a caller's body, read off
    the caller's contract row (``function_universe_outcome``).

    A same-file call is its coordinate ``call:<target>(...)`` and an edge
    to the callee's join symbol, joined at prove (#7757 steps 5 and 6, the
    owner's ruling "Edge, join at prove", #8705): the lifter binds the
    actuals by the one binder (``bind_call``) only to read what the call
    supplies, and never discharges the callee's carrier at the call.  So
    the row's one completed face (under the call's ``completes`` atom)
    returns the call's value, and its term carries what prove's binder
    binds ``helper``'s contract with."""
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    source = (
        f"def helper({signature}):\n    {body}\n\n\n"
        f"def caller():\n    return helper({actuals})\n"
    )
    tree = _tree(source, "unary_call.py")
    caller = next(
        n for n in tree.nodes() if isinstance(n, FunctionDef) and n.name == "caller"
    )
    outcome = function_universe_outcome(caller)
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, outcome
    returns = [
        s for s in completed[0].value.record.statements if isinstance(s, ReturnValue)
    ]
    assert returns, completed[0].value
    edge = returns[-1].value
    assert isinstance(edge, CallSiteValue), type(edge)
    return edge


def _edge_arguments(edge) -> list:
    """The arguments of the call's coordinate ``call:<target>(...)``: the
    completed face of the one unanswered call returns ``python:call_result(
    <call term>, <occurrence>)`` (#7757 steps 5 and 6, #8705), so what
    prove's binder binds is the call term's arguments, never the result's."""
    result = edge.term
    assert result.name == "python:call_result", result
    call = result.args[0]
    assert call.name.startswith("call:"), call
    return list(call.args)


def _int(edge, value: int):
    return TermValue(value).to_term(owner=str(edge.site))


def _kwarg(edge, name: str, value: int):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor("py.kwarg", [str_const(name), _int(edge, value)])


def _default(edge, name: str, value: int):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor("py.default", [str_const(name), _int(edge, value)])


def _int_class(key: str):
    """``py.class(<key>, python:builtin("int"))``: the class of an ``int``
    actual the caller decides, keyed by the argument it is (its position, or
    its keyword), riding after the actuals (#8857,
    ``receiver_dispatch.class_arguments``).  A default supplies none."""
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.receiver_dispatch import (
        CLASS_ARGUMENT,
        builtin_class_term,
    )

    return ctor(CLASS_ARGUMENT, [str_const(key), builtin_class_term("int")])


@dataclass(frozen=True)
class _FloorSugar(ConstructedTermSugar):
    """A constructed operand: every nested term slot admits only a
    ``ConstructedTermSugar`` (``require_constructed_term_sugar``)."""

    value: object

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(self.value)

    def to_term(self, *, owner):
        return self.value.to_term(owner=owner)

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
    assert UnaryOpSugar("USub", _FloorSugar(TermValue(3)), site).desugar(
        None
    ).completed_value() == TermValue(-3)
    assert UnaryOpSugar("UAdd", _FloorSugar(TermValue(3)), site).desugar(
        None
    ).completed_value() == TermValue(3)
    assert UnaryOpSugar("Invert", _FloorSugar(TermValue(5)), site).desugar(
        None
    ).completed_value() == TermValue(~5)


def test_discrimination_neg_is_not_identity() -> None:
    site = _site_from()
    out = UnaryOpSugar("USub", _FloorSugar(TermValue(3)), site).desugar(None)
    assert out.completed_value() == TermValue(-3)
    with pytest.raises(AssertionError):
        assert out.completed_value() == TermValue(3)


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
    _unanswered(pending, {})


def _unanswered(pending, actuals) -> None:
    """An absent actual leaves the operation the cited unanswered face
    (#7825): owed as an ``undecided`` member, never a completed fold."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    exits = pending.discharge(None, actuals)
    assert pending.unanswered_call() in owed_calls(exits)
    assert exits.completed_value() is None


def test_discrimination_helper_alone_is_not_completed() -> None:
    _, pending = _helper("def helper(x):\n    return -x\n")
    with pytest.raises(AssertionError):
        assert isinstance(pending, ExitSet) and pending.completed_value() is not None


def test_not_formal_stays_unary_truth_not_unary_minus() -> None:
    """``not x`` is truth-then-negate; must not steal the arithmetic unary door."""
    _, pending = _helper("def helper(x):\n    return not x\n")
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "unary_truth"
    with pytest.raises(AssertionError):
        assert pending.demand.operator == "unary_minus"


# ---------------------------------------------------------------------------
# Production callers: the call is its coordinate and edge; the edge carries
# what prove's one binder binds the helper's carrier with (#7757 steps 5 and
# 6).  The fold (``-3``) is decided at prove, never at the call.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body,actuals,expected",
    [
        ("return -x", "3", 3),
        ("return +x", "3", 3),
        ("return ~x", "5", 5),
    ],
)
def test_positional_caller_discharges_unary_through_production_binder(
    body: str, actuals: str, expected
) -> None:
    """Real SourceFile caller — not a hand-built coordinate discharge dict.
    The edge carries the positional actual as written."""
    edge = _call_edge("x", body, actuals)
    assert _edge_arguments(edge) == [_int(edge, expected), _int_class("0")]


def test_keyword_caller_discharges_unary_neg() -> None:
    edge = _call_edge("x", "return -x", "x=4")
    assert _edge_arguments(edge) == [_kwarg(edge, "x", 4), _int_class("x")]


def test_default_caller_discharges_unary_neg() -> None:
    # The value the ``def`` statement bound for the default, read where the
    # call runs, is the edge's ``py.default``; prove binds the omitted formal
    # to it.
    edge = _call_edge("x=7", "return -x", "")
    assert _edge_arguments(edge) == [_default(edge, "x", 7)]


def test_positional_keyword_and_default_callers_complete_same_neg_fold() -> None:
    """Binder twins: positional, keyword and default each carry ``x = 3`` in
    the one form prove's binder reads it in."""
    positional = _call_edge("x", "return -x", "3")
    keyword = _call_edge("x", "return -x", "x=3")
    default = _call_edge("x=3", "return -x", "")
    assert _edge_arguments(positional) == [_int(positional, 3), _int_class("0")]
    assert _edge_arguments(keyword) == [_kwarg(keyword, "x", 3), _int_class("x")]
    assert _edge_arguments(default) == [_default(default, "x", 3)]


def test_discrimination_production_neg_is_not_prior_actual() -> None:
    # The call does not apply the helper's body: no folded ``-3`` stands in
    # the caller's row, only the edge with the actual it supplies.
    edge = _call_edge("x", "return -x", "3")
    assert _edge_arguments(edge) == [_int(edge, 3), _int_class("0")]
    assert _int(edge, -3) not in _edge_arguments(edge)


# ---------------------------------------------------------------------------
# Wrong-coordinate / missing-actual: no fabricated completion
# ---------------------------------------------------------------------------


def test_wrong_coordinate_actual_cannot_discharge_pending_unary() -> None:
    """Swapped/wrong coordinate keys must not fabricate a Completed fold."""
    function, pending = _helper("def helper(x):\n    return -x\n")
    assert isinstance(pending, NativeOperationExitCarrierV1)
    (coord,) = function.formal_coordinates()
    _unanswered(pending, {f"wrong:{coord.coordinate_cid}": TermValue(3)})


def test_missing_actual_does_not_fabricate_completed_neg() -> None:
    """Empty discharge stays undischarged — never Completed TermValue(0) etc."""
    _, pending = _helper("def helper(x):\n    return -x\n")
    assert isinstance(pending, NativeOperationExitCarrierV1)
    _unanswered(pending, {})


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
        assert out.completed_value() is not None


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
    """Discharge projectors are unary Floor methods — arity 1 + site + ctx."""
    import inspect

    for name in ("unary_minus", "unary_plus", "bitwise_invert"):
        projector = _NATIVE_OPERATION_PROJECTORS[name]
        # site, then the caller's ctx, are last; one operand.
        assert len(inspect.signature(projector).parameters) == 3
    negated = _NATIVE_OPERATION_PROJECTORS["unary_minus"](TermValue(4), "s", None)
    assert negated.completed_value() == TermValue(-4)
    with pytest.raises(AssertionError):
        # Lying: unary_minus is not add-shaped (2 operands + site + ctx).
        assert (
            len(
                inspect.signature(
                    _NATIVE_OPERATION_PROJECTORS["unary_minus"]
                ).parameters
            )
            == 4
        )
