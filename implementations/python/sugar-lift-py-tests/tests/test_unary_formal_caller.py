"""Formal unary operators: ``-x``, ``+x``, ``~x``.

Law (#7757 NEW-1):

  - a formal operand → the undecided two faces (``FloorValue.undecided_unary``):
    completes under ``python:<neg|pos|invert>.completes``, halts undetermined
    under the complement, owed either way; no carrier waits on a caller
  - production caller (positional / keyword / default) → the call is its
    coordinate and edge, joined at prove
  - open (non-formal) SymbolicValue still refuses inventing success vs TypeError
  - ground production folds
  - ``not x`` is the truth rule's two faces, then negation, never ``-x``
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
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
# A formal operand: the undecided two faces (helper alone — no caller)
# ---------------------------------------------------------------------------


def _undecided_halts(outcome, owner: str) -> list:
    """The undetermined halts ``owner`` minted in ``outcome``."""
    return [
        arm
        for arm in outcome.exits
        if isinstance(arm, Halted)
        and type(arm.effect) is UndeterminedRaiseEffect
        and arm.effect.producer_node_owner == owner
    ]


def _two_faced(outcome, owner: str) -> None:
    """No carrier: the outcome keeps the operation's undetermined halt
    (``owner``) beside its completion, and owes the operation."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    assert isinstance(outcome, ExitSet), type(outcome)
    assert _undecided_halts(outcome, owner), outcome
    assert any(isinstance(arm, Completed) for arm in outcome.exits), outcome
    assert owed_calls(outcome), outcome


@pytest.mark.parametrize(
    "source,method",
    [
        ("def helper(x):\n    return -x\n", "unary_minus"),
        ("def helper(x):\n    return +x\n", "unary_plus"),
        ("def helper(x):\n    return ~x\n", "bitwise_invert"),
    ],
)
def test_helper_alone_is_the_undecided_two_faces(source: str, method: str) -> None:
    """#7757 NEW-1: ``-x`` / ``+x`` / ``~x`` on a parameter mints no carrier
    waiting on a caller production never supplies; it is the undecided two
    faces, owed, its halt kept."""
    _, outcome = _helper(source)
    _two_faced(outcome, f"SymbolicValue.{method}")


def test_discrimination_helper_alone_is_not_completed() -> None:
    _, outcome = _helper("def helper(x):\n    return -x\n")
    with pytest.raises(AssertionError):
        assert isinstance(outcome, ExitSet) and outcome.completed_value() is not None


def test_not_formal_is_truth_then_negate_not_unary_minus() -> None:
    """``not x`` is truth-then-negate; must not steal the arithmetic unary door.
    The truth is the one truth rule's two faces (#7757 NEW-1)."""
    _, outcome = _helper("def helper(x):\n    return not x\n")
    _two_faced(outcome, "UnaryOpSugar.not")
    assert not _undecided_halts(outcome, "SymbolicValue.unary_minus")


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
# Nothing waits on a caller: no fabricated completion, nothing to discharge
# ---------------------------------------------------------------------------


def test_a_formal_unary_completes_only_under_its_undecided_atom() -> None:
    """The completed face is the undecided
    ``python:unary_result("-", x, <key>)`` under ``python:unary_op.completes``,
    never a folded value: no ``TermValue`` is fabricated without an actual."""
    site = _site_from()
    function, _outcome = _helper("def helper(x):\n    return -x\n")
    (coord,) = function.formal_coordinates()
    formal = SymbolicValue(make_var("x"), coord)
    faces = UnaryOpSugar("USub", _FloorSugar(formal), site).desugar(None)
    (done,) = [arm for arm in faces.exits if isinstance(arm, Completed)]
    assert "python:unary_op.completes" in repr(done.guard)
    assert "python:unary_result" in repr(done.value)
    assert not isinstance(done.value, TermValue)
    assert faces.completed_value() is None


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
