"""A method call applies its body through the one application routine (#7756).

A plain call ``f(...)`` runs ``f``'s body through ``CallSiteValue.producer_outcome``
and carries every face of it: completions and raises.  A bound method call
``obj.m(...)`` is the same application with the receiver bound as the first
actual (``object_value.apply_bound_method``), so a method that raises leaves its
caller raising.

Each pair differs in exactly one thing and goes through the real solver:
the truthful source's claim holds (``sat``); the lying source makes the method
raise, so the assertion after the call is never reached (``unsat``).
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
        return item.desugar(ctx).value.project_operation_receiver(
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
    assert t.verdict == "sat"
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


@pytest.mark.parametrize("form", sorted(_IN_PROCESS_PAIRS))
def test_method_raise_reaches_the_caller_in_process(form: str) -> None:
    from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted

    truthful, lying, exception = _IN_PROCESS_PAIRS[form]
    assert isinstance(_test_function_outcome(truthful), Complete)
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
# verdict for a program whose call may raise (and, with an undefined receiver,
# does).  ``open`` is this twin stating "not bridged"; it is not a green
# truthful half, and it becomes ``sat`` only when something decides the call.
#
# The call's other face is a raise.  A raise is not a refutation, and the
# solver gives no verdict on it until halted arms are emitted from the
# reduction (#7766), so the raise face is shown at the reduction level below
# and no ``unsat`` is asserted for it.
# ---------------------------------------------------------------------------

_UNKNOWN_RECEIVER = """\
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
    from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted

    assert isinstance(_test_function_outcome(_HELD_RECEIVER), Complete)
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


_UNCONSTRUCTED_METHOD = """\
class Box:
    def kept(self):
        return 1

    def left_out(self{formal}):
        return 2


def test_box():
    box = Box()
    assert box.left_out({actual}) == 2
"""


@pytest.mark.parametrize(
    ("formal", "actual", "observed"),
    [
        ("", "", "Box.left_out has no source frame (body DeferredMethodBodySugar)"),
        (", x", "", "observed=Box.left_out "),
        (", x", "x=2", "observed=Box.left_out "),
    ],
)
def test_a_method_with_no_source_frame_is_not_bound(
    formal: str, actual: str, observed: str
) -> None:
    """Only a source frame binds a call's actuals.

    A class projected to some of its methods (the door manager construction
    uses) binds the others without constructing them: they carry no frame.
    Calling one refuses by name, whatever its arity; nothing takes the actuals
    as already being in formal order.
    """
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_source_tree.nodes import PROJECTED_CLASS_METHODS

    token = PROJECTED_CLASS_METHODS.set({"Box": frozenset({"kept"})})
    try:
        with pytest.raises(ConstructionPanic) as refusal:
            _test_function_outcome(
                _UNCONSTRUCTED_METHOD.format(formal=formal, actual=actual)
            )
    finally:
        PROJECTED_CLASS_METHODS.reset(token)
    assert observed in str(refusal.value), str(refusal.value)
    assert "owner=MethodCallSugar" in str(refusal.value)
