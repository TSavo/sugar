"""A method called on a ``ContextVar.get()`` read is two-faced.

The read is one occurrence's own value (whatever the running context holds),
held by this frame as itself, like a call's result.  No floor decides its
type, so ``format_options.get().copy()`` (numpy's ``get_printoptions``) may
raise: it completes only under ``python:unknown_callee_call.completes(...)`` and
halts with an ``UndeterminedRaiseEffect`` (owner
``UnknownCallee:copy``).  It used to complete totally.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.language_owned_contextvar import (
    LanguageOwnedContextVarReadValue,
)
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted, outcome_to_exitset
from sugar_lift_py_tests.sugar.method_call_sugar import dispatch_method_call


def test_a_method_on_a_contextvar_read_may_raise(tmp_path):
    read = LanguageOwnedContextVarReadValue(
        variable_name="v", site="get-site", occurrence="get-site"
    )
    exits = outcome_to_exitset(
        dispatch_method_call("copy", read, (), (), "copy-site", None)
    ).exits
    (done,) = [face for face in exits if isinstance(face, Completed)]
    (halt,) = [face for face in exits if isinstance(face, Halted)]
    assert "python:unknown_callee_call.completes" in str(done.guard)
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "UnknownCallee:copy"
