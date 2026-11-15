"""A method called on a ``with ... as v`` enter result may raise.

The body reads ``v`` through the With's enter-result slot.  Method dispatch
treated that slot like a field coordinate that a later store application
would replace, so it minted no face and ``v.write(...)`` completed totally.
No later store application replaces an enter-result slot.  So a method called
on it runs on exactly the value ``__enter__`` returned, and when no floor
projects the method body the call is two-faced (#7585): it completes under
``python:unknown_callee_call.completes`` and otherwise halts with an
``UndeterminedRaiseEffect`` owned by ``UnknownCallee:<name>``.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

from test_undetermined_raise_except_matching import _exits


@pytest.mark.parametrize(
    "source",
    [
        # Opaque C enter result: the decimal case and builtin ``open``.
        "import decimal\ndef f(p):\n    with decimal.localcontext() as fh:\n"
        "        fh.write('x')\n    return 1\n",
        "def f(p):\n    with open(p) as fh:\n        fh.write('x')\n    return 1\n",
    ],
)
def test_method_on_enter_result_is_two_faced(tmp_path, source):
    exits = _exits(tmp_path, source).exits
    owners = [
        face.effect.producer_node_owner
        for face in exits
        if isinstance(face, Halted) and isinstance(face.effect, UndeterminedRaiseEffect)
    ]
    assert "UnknownCallee:write" in owners
    completed = [face for face in exits if isinstance(face, Completed)]
    assert completed
    assert all("python:unknown_callee_call.completes" in repr(face.guard) for face in completed)


def test_method_on_a_source_enter_result_runs_its_body(tmp_path):
    """A source manager whose ``__enter__`` returns ``self``: ``fh`` is that
    instance (the value ``__enter__`` returned), so ``fh.write('x')`` runs
    ``M.write``, which always raises ``ValueError``.  Never total, and never
    the unknown callee: the method the instance's class holds is applied."""
    source = (
        "class M:\n    def __enter__(self):\n        return self\n"
        "    def __exit__(self, *a):\n        return None\n"
        "    def write(self, v):\n        raise ValueError\n"
        "def f(p):\n    with M() as fh:\n        fh.write('x')\n    return 1\n"
    )
    exits = _exits(tmp_path, source).exits
    halts = [face.effect for face in exits if isinstance(face, Halted)]
    assert not any(
        isinstance(effect, UndeterminedRaiseEffect)
        and effect.producer_node_owner == "UnknownCallee:write"
        for effect in halts
    )
    assert any(
        not isinstance(effect, UndeterminedRaiseEffect)
        and getattr(effect, "exception_name", None) == "ValueError"
        for effect in halts
    )
