"""``import contextvars`` then ``contextvars.ContextVar(...)`` is the same ContextVar.

#7646 floored a function's read of a module-built ContextVar only for
``from contextvars import ContextVar``.  The module-attribute spelling,
``import contextvars [as m]; v = m.ContextVar("v", default=...)``, reaches the
same class through a module name bound exactly once.  So the same law applies:
``v.get()`` is one opaque read, and ``.copy()`` on it is two-faced.  It used to
complete with no failure case.  Any other binding of the module name keeps
the free Var.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
from sugar_lift_python_source.language_owned_c_export import (
    source_contextvar_global_read,
)

from test_undetermined_raise_except_matching import _exits

_BODY = "def f():\n    return v.get().copy()\n"


@pytest.mark.parametrize(
    "prefix",
    [
        "import contextvars\nv = contextvars.ContextVar('v', default={})\n",
        "import contextvars as cv\nv = cv.ContextVar('v', default={})\n",
    ],
)
def test_copy_of_the_read_is_two_faced(tmp_path, prefix):
    exits = _exits(tmp_path, prefix + _BODY).exits
    (done,) = [face for face in exits if isinstance(face, Completed)]
    (halt,) = [face for face in exits if isinstance(face, Halted)]
    assert "python:unknown_callee_call.completes" in str(done.guard)
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "UnknownCallee:copy"


def test_a_rebound_module_name_is_not_contextvars():
    source = (
        "import contextvars\ncontextvars = object()\n"
        "v = contextvars.ContextVar('v', default={})\n" + _BODY
    )
    assert source_contextvar_global_read(source, "v", 5, 11) is None
    other = "import other as contextvars\nv = contextvars.ContextVar('v')\n" + _BODY
    assert source_contextvar_global_read(other, "v", 4, 11) is None
