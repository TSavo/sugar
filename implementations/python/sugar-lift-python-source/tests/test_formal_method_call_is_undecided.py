"""A method call on a formal never waits for a caller's actual (#7757 NEW-1).

``def f(y): return y.foo()`` once deferred through
``NativeOperationExitCarrierV1`` with the ``method_call`` operator, waiting
for the caller's actual to select the method.  Production never discharges a
carrier with actuals (only with none, ``tree_enumerate``), so the carrier
ended as the one owed ``undecided`` member: the same debt the unanswered call
states, written a second way.  The carrier, its mint and its projector are
deleted.  A method call on a formal is now one of:

- the dispatched edge (``call:dispatch:<m>``, ``receiver_dispatch.
  dispatch_on_receiver``) where the formal's class is an input of the
  function's contract: prove resolves it where a caller binds the class;
- else the one unanswered call (``UnknownCalleeCallV1``): it completes under
  its own ``completes`` atom and owes the ``undecided`` member, or raises an
  ``UndeterminedRaiseEffect``;
- a formal operand of a receiver the lift decides: that receiver's own floor,
  or the unanswered call where no floor answers, as for any operand it cannot
  read.

What a decided actual does when a caller supplies one is the one dispatch on
that actual (``dispatch_method_call``), pinned here directly: a floor's
method body, the container law (#7603), or the two faces of a method no
floor answers (#7616).
"""

from __future__ import annotations

from sugar_lift_py_tests.floor import ListValue, StringValue, TermValue
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.method_call_sugar import dispatch_method_call
from sugar_source_tree.nodes import FunctionDef

from frame_fresh import fresh
from test_contextlib_suppress_source_exit_faces import _corpus, _open
from test_unprojected_method_call_faces import _owners, _split


class _Site:
    """A fragment's two coordinates: its unit's source CID and its span."""

    class _Span:
        start_line, start_col, end_line, end_col = 2, 11, 2, 18

    source_cid = "blake3-512:" + "e" * 128
    line_col_span = _Span()


def _outcome(tmp_path, source):
    """``f``'s own reduction: an exit set, never a carrier waiting for an
    actual."""
    source_file = _open(_corpus(tmp_path, source))
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    outcome = func.sugar().desugar()
    assert isinstance(outcome, ExitSet), type(outcome)
    return outcome


def _halt_owners(outcome):
    return sorted(
        str(getattr(face.effect, "producer_node_owner", None))
        for face in outcome.exits
        if isinstance(face, Halted)
    )


def _on_actual(name, actual, positional=(), keywords=()):
    """The call on a caller's decided actual: the one dispatch."""
    return dispatch_method_call(
        name, actual, tuple(positional), tuple(keywords), _Site(), None
    )


def _faces(exits):
    completed = [face.value for face in exits.exits if isinstance(face, Completed)]
    halted = [face.effect for face in exits.exits if isinstance(face, Halted)]
    return completed, halted


def test_a_formal_whose_class_is_an_input_is_the_dispatched_edge(tmp_path):
    # ``y`` is read only as a receiver: its class is ``f``'s ``class:y``
    # input, so the call is the dispatched edge, its halt kept.
    outcome = _outcome(tmp_path, "def f(y):\n    return y.foo()\n")
    assert "UnknownCallee:dispatch:foo" in _halt_owners(outcome)
    assert any(isinstance(face, Completed) for face in outcome.exits)


def test_keyword_actuals_on_an_undecided_formal_keep_both_faces(tmp_path):
    # ``y`` is read bare (``z = y``), so its class is no input: nothing would
    # ever bind it.  The call is the one unanswered call, both faces kept
    # (``test_unprojected_method_call_faces`` pins the plain call).
    returns, halts = _split(
        tmp_path, "def f(y):\n    z = y\n    return y.foo(1, k=2)\n"
    )
    assert len(returns) == 1
    assert _owners(halts) == ["UnknownCallee:foo"]


def test_a_formal_operand_never_defers(tmp_path):
    # The receiver is the lift's own ``str``; no floor of it answers
    # ``index`` over an operand it cannot read, so the call is the
    # unanswered call, not a carrier waiting for ``y``.
    outcome = _outcome(tmp_path, "def f(y):\n    return 'a'.index(y)\n")
    assert "UnknownCallee:index" in _halt_owners(outcome)


def test_a_str_actual_is_the_two_faces():
    _completed, halted = _faces(_on_actual("foo", StringValue("a")))
    assert _owners(halted) == ["UnknownCallee:foo"]


def test_a_list_actual_takes_the_container_law():
    completed, halted = _faces(
        _on_actual("append", fresh(ListValue, ()), (TermValue(1),))
    )
    assert completed == [NoneValue()]
    assert halted == []


def test_a_contents_read_is_two_faced():
    # Whether ``pop`` raises reads the contents, which the law does not
    # decide for a mutating method.
    _completed, halted = _faces(_on_actual("pop", fresh(ListValue, (TermValue(5),))))
    assert _owners(halted) == ["BuiltinMethodCall:list.pop"]


def test_keyword_actuals_reach_the_dispatch():
    _completed, halted = _faces(
        _on_actual("foo", StringValue("a"), (TermValue(1),), (("k", TermValue(2)),))
    )
    assert _owners(halted) == ["UnknownCallee:foo"]


# A caller never runs a same-file helper's body on its actual (#8705): the
# call is its coordinate and edge, and the dispatch above is what ``g``'s
# contract states over its formal, joined at prove (#7757 steps 6 and 9).  So
# each helper call below keeps the one halt its edge owes, and no face the
# lift would read off ``g``'s body on the caller's actual.


def test_a_helper_pop_on_an_empty_actual_is_the_helpers_edge(tmp_path):
    source = "def g(y):\n    return y.pop()\ndef f():\n    return g([])\n"
    _returns, halts = _split(tmp_path, source)
    assert _owners(halts) == ["UnknownCallee:e.g"]


def test_a_helper_append_leaves_the_calls_after_state(tmp_path):
    from test_builtin_container_mutation import _is_after_call

    source = (
        "def g(y):\n"
        "    y.append(1)\n"
        "def f():\n"
        "    r = []\n"
        "    g(r)\n"
        "    return r\n"
    )
    returns, halts = _split(tmp_path, source)
    (value,) = returns
    assert _is_after_call(value, "y", callee="e.g")
    assert value != fresh(ListValue, ())
    assert value != fresh(ListValue, (TermValue(1),))
    assert _owners(halts) == ["UnknownCallee:e.g"]


def test_a_source_method_on_a_formal_is_the_helpers_edge(tmp_path):
    source = (
        "class C:\n"
        "    def m(self):\n"
        "        return 1\n"
        "def g(y):\n"
        "    return y.m()\n"
        "def f():\n"
        "    return g(C())\n"
    )
    _returns, halts = _split(tmp_path, source)
    assert _owners(halts) == ["UnknownCallee:e.C", "UnknownCallee:e.g"]
