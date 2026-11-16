"""Keyword arguments and spreads ride the call bridge coordinate faithfully."""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        # The callee ``f`` is bound by nothing the module reads: a star import
        # it cannot read may bind it, so it is the unanswered callee, never a
        # NameError (``NameSugar.desugar``, ``name_bound_nowhere``).
        f.write("from unread_module import *\n" + src)
        path = f.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())


def _out(src):
    """The call term the function returns.

    A call nothing answers is the unanswered call's two faces
    (``UnknownCalleeCallV1``): it completes only under its own completes
    atom, with ``python:call_result(<call term>, <occurrence>)`` as its
    value, and its halt is kept beside it."""
    from sugar_lift_py_tests.outcome import Completed, ExitSet
    from sugar_lift_py_tests.outcome.exit_set import _is_true

    outcome = _fn(src).sugar().desugar()
    assert isinstance(outcome, ExitSet), outcome
    assert any(
        str(getattr(halt.effect, "producer_node_owner", "")).startswith(
            "UnknownCallee:"
        )
        for halt in outcome.halts()
    ), outcome.exits
    completed = [e for e in outcome.normalize().exits if isinstance(e, Completed)]
    assert len(completed) == 1, outcome.exits
    assert not _is_true(completed[0].guard), completed[0].guard
    result = completed[0].value.post().args[1]
    assert result.name == "python:call_result", result
    return result.args[0]


def test_named_call_kwarg_lifts():
    t = _out("def A(x):\n    return f(x, k=1)\n")
    assert t.name == "call:f"
    kwarg = t.args[-1]
    assert kwarg.name == "py.kwarg"
    assert kwarg.args[0].value == "k"
    assert kwarg.args[1].value == 1


def test_method_call_kwarg_lifts():
    # A method on a formal is the dispatched call (``receiver_dispatch``):
    # its receiver's class rides after the written actuals.
    t = _out("def A(z):\n    return z.get(1, default=2)\n")
    assert t.name == "call:dispatch:get"
    (kwarg,) = [arg for arg in t.args if arg.name == "py.kwarg"]
    assert kwarg.args[0].value == "default"
    assert kwarg.args[1].value == 2


def test_kwarg_value_discriminates():
    t1 = _out("def A(x):\n    return f(x, k=1)\n")
    t2 = _out("def A(x):\n    return f(x, k=2)\n")
    assert t1.args[-1].args[1].value != t2.args[-1].args[1].value
    assert t1 != t2


def test_named_call_spread_builds_reference_call_operand():
    t = _out("def A(x, d):\n    return f(x, **d)\n")

    assert t.name == "python:call"
    assert t.args[0].value == "f"
    spread = t.args[-1]
    assert spread.name == "python:double_starred_kwarg"
    assert spread.args[0].name == "d"
