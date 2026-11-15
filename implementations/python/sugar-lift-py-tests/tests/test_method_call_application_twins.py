"""A method call applies its body through the one application routine (#7756).

A plain call ``f(...)`` runs ``f``'s body through ``CallSiteValue.producer_outcome``
and carries every face of it: completions and raises.  A bound method call
``obj.m(...)`` is the same application with the receiver bound as the first
actual (``object_value.apply_bound_method``), so a method that raises leaves its
caller raising.

Each pair differs in exactly one thing and goes through the real solver.  The
lying source makes the method raise, so the assertion after the call is never
reached (``unsat``).  The truthful source's claim is not decided (``open``):
every truthful method body reads its arrived ``self`` (``return self.n``) or
calls a method on it (``self.check()``, ``self.open(...)``), and a receiver
that reached a frame by binding is read undecided there -- a subclass may
override the method or the field may be anything (#8151, #8153).  ``open`` is
the truthful verdict, not a missing ``sat``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def bound_method_call_at(call_node, ctx=None):
    """The method call at ``call_node`` as bound, before it is applied.

    ``receiver.m(args)`` desugars to ``m(receiver, args)`` bound by the
    receiver's ``bound_method_call`` and applied once by
    ``CallSiteValue.producer_outcome``.  Unit tests that inspect the binding
    (the receiver in slot 0, the actuals in formal order) read it here; the
    Call itself yields the applied outcome.
    """
    sugar = call_node.sugar()

    def operand(item):
        return item.desugar(ctx).completed_value().project_operation_receiver(
            ctx, owner="bound_method_call_at"
        )

    return operand(sugar.receiver).bound_method_call(
        sugar.name,
        tuple(operand(argument) for argument in sugar.args),
        owner="bound_method_call_at",
        blame=sugar.site,
        ctx=ctx,
        keywords=tuple((name, operand(value)) for name, value in sugar.keywords),
        required_frame=sugar.source_call_frame,
    )


def _pair(tmp_path: Path, name: str, truthful: str, lying: str) -> None:
    t = run_source_through_real_solver(tmp_path / f"{name}-truthful", truthful)
    lie = run_source_through_real_solver(tmp_path / f"{name}-lying", lying)
    print(json.dumps({"truthful": t.verdict, "lying": lie.verdict}, sort_keys=True))
    # The truthful body reads the arrived ``self``: the undecided read or
    # call (#8153), so its claim is ``open``.  See the module docstring.
    assert t.verdict == "open"
    assert lie.verdict == "unsat"


_OBJ_CALL = """\
class Gauge:
    def __init__(self, n):
        self.n = n

    def read(self):
{body}


def test_gauge():
    gauge = Gauge(4)
    value = gauge.read()
    assert value == 4
"""


def test_receiver_method_call_carries_the_method_raise(tmp_path: Path) -> None:
    """``obj.m()``: ``m`` completes vs ``m`` always raises."""

    _pair(
        tmp_path,
        "obj-call",
        _OBJ_CALL.format(body="        return self.n"),
        _OBJ_CALL.format(body="        raise KeyError('no reading')"),
    )


_SELF_CALL = """\
class Box:
    def __init__(self, n):
        self.n = n

    def run(self):
        state = self.check()
        return self.n

    def check(self):
{body}


def test_box():
    box = Box(3)
    value = box.run()
    assert value == 3
"""


def test_self_method_call_carries_the_method_raise(tmp_path: Path) -> None:
    """``self.m()`` inside a method: ``m`` completes vs ``m`` always raises."""

    _pair(
        tmp_path,
        "self-call",
        _SELF_CALL.format(body="        return None"),
        _SELF_CALL.format(body="        raise ValueError('bad box')"),
    )


_ONE_BRANCH = """\
class Limit:
    def __init__(self, n):
        self.n = n

    def run(self, n):
        state = self.check(n=n)
        return state

    def check(self, n):
        if n > 5:
            raise ValueError('too big')
        return n


def test_limit():
    limit = Limit(0)
    value = limit.run({actual})
    assert value == {actual}
"""


def test_method_raising_on_one_branch_carries_that_raise(tmp_path: Path) -> None:
    """``self.m(n=n)`` raising on one branch: the actual selects the arm."""

    _pair(
        tmp_path,
        "one-branch",
        _ONE_BRANCH.format(actual=3),
        _ONE_BRANCH.format(actual=9),
    )


_SUPER_CALL = """\
class Base:
    def check(self):
{body}


class Child(Base):
    def __init__(self, n):
        self.n = n

    def run(self):
        state = super().check()
        return self.n


def test_child():
    child = Child(2)
    value = child.run()
    assert value == 2
"""


def test_super_method_call_carries_the_method_raise(tmp_path: Path) -> None:
    """``super().m()``: the base method completes vs always raises."""

    _pair(
        tmp_path,
        "super-call",
        _SUPER_CALL.format(body="        return None"),
        _SUPER_CALL.format(body="        raise ValueError('bad base')"),
    )


_SPREAD_CALL = """\
class Store:
    def __init__(self):
        self.mode = 'r'

    def run(self, **kwargs):
        handle = self.open(**kwargs)
        return 1

    def open(self, mode='r'):
{body}


def test_store():
    store = Store()
    value = store.run(mode='r')
    assert value == 1
"""


def test_spread_method_call_carries_the_method_raise(tmp_path: Path) -> None:
    """``self.m(**kwargs)``: the method completes vs always raises."""

    _pair(
        tmp_path,
        "spread-call",
        _SPREAD_CALL.format(body="        return mode"),
        _SPREAD_CALL.format(body="        raise OSError('cannot open')"),
    )


# ---------------------------------------------------------------------------
# The same pairs in process (a unit check, not a twin): the lifter's own
# outcome for the test function.  Truthful completes; lying carries only the
# method's raise.  Before #7756 every lying source here completed.
# ---------------------------------------------------------------------------


_IN_PROCESS_PAIRS = {
    "obj-call": (
        _OBJ_CALL.format(body="        return self.n"),
        _OBJ_CALL.format(body="        raise KeyError('no reading')"),
        "KeyError",
    ),
    "self-call": (
        _SELF_CALL.format(body="        return None"),
        _SELF_CALL.format(body="        raise ValueError('bad box')"),
        "ValueError",
    ),
    "one-branch": (
        _ONE_BRANCH.format(actual=3),
        _ONE_BRANCH.format(actual=9),
        "ValueError",
    ),
    "super-call": (
        _SUPER_CALL.format(body="        return None"),
        _SUPER_CALL.format(body="        raise ValueError('bad base')"),
        "ValueError",
    ),
    "spread-call": (
        _SPREAD_CALL.format(body="        return mode"),
        _SPREAD_CALL.format(body="        raise OSError('cannot open')"),
        "OSError",
    ),
}


def _test_function_outcome(source: str):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree.nodes import FunctionDef
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name.startswith("test_")
    )
    return function_universe_outcome(function)


# Inside a method, ``self`` is a formal: the receiver reaches the body by
# binding (``object_identity.arrived``), so its fields are not current there
# and an explicit ``self.<name>`` -- a field or a method, read through
# ``ObjectValue.attribute`` -- is the undecided read: a completion under
# ``python:attribute.completes`` and an undetermined raise (#8151, #8153).
#
# - ``obj-call``: ``gauge.read()`` is selected in the test function, where
#   ``gauge`` is current, so the lying body's ``KeyError`` reaches the caller;
#   the truthful body's ``return self.n`` is the undecided read.
# - ``self-call``, ``one-branch``, ``spread-call``: the call that raises is
#   itself ``self.check(...)`` / ``self.open(...)`` on the arrived receiver,
#   so neither half selects the method: both are the undecided call, and no
#   named raise is decided for either.
# - ``super-call``: the base method is selected through ``super()``, which
#   walks ``type(self).__mro__`` and reads no field, so the lying body's
#   ``ValueError`` reaches the caller.  The truthful body's ``return self.n``
#   reads the same arrived ``self`` as ``obj-call``'s: ``Base.check`` stores
#   nothing on it, so nothing after the call makes ``self.n`` known, and the
#   receiver after the call is the arrived one
#   (``call_site_value.receiver_after_its_call``): the undecided read.
_SELECTED_ON_THE_CALLER = ("obj-call", "super-call")
_SELECTED_THROUGH_AN_ARRIVED_SELF = ("one-branch", "self-call", "spread-call")


def _undecided_faces(outcome) -> None:
    """A completed face under an undecided read's guard, and every halt an
    undetermined raise: nothing about the read is decided, no exception is
    named."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet), outcome
    assert outcome.completed_value() is None, outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    halted = [face for face in outcome.exits if isinstance(face, Halted)]
    assert completed and halted, outcome
    for halt in halted:
        assert isinstance(halt.effect, UndeterminedRaiseEffect), halt.effect
        assert halt.effect.exception_name is None, halt.effect


@pytest.mark.parametrize("form", sorted(_IN_PROCESS_PAIRS))
def test_method_raise_reaches_the_caller_in_process(form: str) -> None:
    from sugar_lift_py_tests.outcome import ExitSet, Halted

    truthful, lying, exception = _IN_PROCESS_PAIRS[form]
    if form in _SELECTED_THROUGH_AN_ARRIVED_SELF:
        _undecided_faces(_test_function_outcome(truthful))
        _undecided_faces(_test_function_outcome(lying))
        return
    assert form in _SELECTED_ON_THE_CALLER, form
    _undecided_faces(_test_function_outcome(truthful))
    outcome = _test_function_outcome(lying)
    assert isinstance(outcome, ExitSet), outcome
    assert [type(face) for face in outcome.exits] == [Halted]
    assert outcome.exits[0].effect.exception_name == exception


# ---------------------------------------------------------------------------
# A method call on a receiver the lifter does not have is the plain call to a
# callee it does not have: two faces (#7756).  Before, it completed alone.
#
# What the rule claims, through the solver: what is asserted after the call is
# asserted on the call's completing face, and that face stands under
# ``python:unknown_callee_call.completes``, which nothing here decides.  So a
# true claim after the call is not decided (``open``): nothing proves the call
# completes.  A false claim is refuted on every face (``unsat``).  Before this
# change the call completed alone and the true claim came back ``sat``: a
# verdict for a program whose call may raise.  ``open`` is this twin stating
# "not bridged"; it is not a green truthful half, and it becomes ``sat`` only
# when something decides the call.
#
# The call's other face is a raise.  A raise is not a refutation, and the
# solver gives no verdict on it until halted arms are emitted from the
# reduction (#7766), so the raise face is shown at the reduction level below
# and no ``unsat`` is asserted for it.
#
# The receiver is a name only a star import the lifter cannot read may bind:
# a free operand nothing decides, the receiver this rule is about.  A name the
# module binds nowhere is no free operand: its read halts with ``NameError``
# (``NameSugar``, #7854) before the call, so no assertion is reached.
# ---------------------------------------------------------------------------

_UNKNOWN_RECEIVER = """\
from unread_module import *


def test_lookup():
    registry = undefined_registry
    value = registry.lookup(3)
    assert 3 == {claim}
"""


def test_a_claim_after_an_unknown_receiver_method_call_stands_on_its_completing_face(
    tmp_path: Path,
) -> None:
    true_claim = run_source_through_real_solver(
        tmp_path / "true-claim", _UNKNOWN_RECEIVER.format(claim=3)
    )
    false_claim = run_source_through_real_solver(
        tmp_path / "false-claim", _UNKNOWN_RECEIVER.format(claim=4)
    )
    print(
        json.dumps(
            {"true-claim": true_claim.verdict, "false-claim": false_claim.verdict},
            sort_keys=True,
        )
    )
    assert true_claim.verdict == "open"
    assert false_claim.verdict == "unsat"


_HELD_RECEIVER = """\
class Registry:
    def lookup(self, key):
        return key


def test_lookup():
    registry = Registry()
    value = registry.lookup(3)
    assert 3 == 3
"""


def test_unknown_receiver_method_call_is_two_faced_in_process() -> None:
    """Reduction level: the completion is guarded and the raise is a face.

    A receiver the lifter holds applies the method body and completes alone;
    a receiver it does not hold is the plain unknown call, completing only
    under ``python:unknown_callee_call.completes`` and raising otherwise.
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert _test_function_outcome(_HELD_RECEIVER).completed_value() is not None
    outcome = _test_function_outcome(_UNKNOWN_RECEIVER.format(claim=3))
    assert isinstance(outcome, ExitSet), outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    halted = [face for face in outcome.exits if isinstance(face, Halted)]
    assert completed and halted
    assert all(
        "python:unknown_callee_call.completes" in repr(face.guard)
        for face in completed
    )
    assert any(
        isinstance(face.effect, UndeterminedRaiseEffect)
        and face.effect.producer_node_owner == "UnknownCallee:lookup"
        for face in halted
    )
