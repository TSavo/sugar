"""A module's function reading the ContextVar that module builds itself.

``from contextvars import ContextVar`` plus a single module-level
``v = ContextVar("v"[, default=...])`` makes ``v`` the language-owned
ContextVar (the same law as an imported one, #7625).  A function body's read of
``v`` used to stay a free ``Var`` that "a later store application supplies".
Nothing supplies it, so ``v.get().copy()`` completed totally.  Now the read is
the ContextVar, ``v.get()`` is one opaque occurrence read, and ``.copy()`` on
that read is two-faced (#7636).  ``set`` mints its token.  ``get`` with no
default may raise LookupError, so it refuses by name instead of completing.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.language_owned_contextvar import (
    LanguageOwnedContextVarReadValue,
    LanguageOwnedContextVarToken,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

from test_undetermined_raise_except_matching import _exits

_PREFIX = "from contextvars import ContextVar\nv = ContextVar('v', default={})\n"


def test_copy_of_a_consumer_built_contextvar_read_is_two_faced(tmp_path):
    exits = _exits(tmp_path, _PREFIX + "def f():\n    return v.get().copy()\n").exits
    (done,) = [face for face in exits if isinstance(face, Completed)]
    (halt,) = [face for face in exits if isinstance(face, Halted)]
    assert "python:unknown_callee_call.completes" in str(done.guard)
    (receiver,) = [
        value
        for value in done.value.record.statements[0].value.arg_values
        if isinstance(value, LanguageOwnedContextVarReadValue)
    ]
    assert receiver.variable_name == "v"
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "UnknownCallee:copy"


def test_set_on_a_consumer_built_contextvar_mints_its_token(tmp_path):
    exits = _exits(tmp_path, _PREFIX + "def f():\n    return v.set(1)\n").exits
    (done,) = exits
    assert isinstance(done.value.record.statements[0].value, LanguageOwnedContextVarToken)


def test_get_without_a_default_refuses_by_name(tmp_path):
    source = (
        "from contextvars import ContextVar\nv = ContextVar('v')\n"
        "def f():\n    return v.get()\n"
    )
    with pytest.raises(ConstructionPanic):
        _exits(tmp_path, source)


def test_only_an_unshadowed_function_body_read_is_the_global():
    from sugar_lift_python_source.language_owned_c_export import (
        source_contextvar_global_read,
    )

    body = _PREFIX + "def f():\n    return v.get()\n"
    assert source_contextvar_global_read(body, "v", 4, 11).name == "v"
    # Module level, before or after the binding, is not a function body read.
    assert source_contextvar_global_read(body, "v", 2, 0) is None
    param = _PREFIX + "def f(v):\n    return v.get()\n"
    assert source_contextvar_global_read(param, "v", 4, 11) is None
    rebound = body + "def g():\n    global v\n    v = 1\n"
    assert source_contextvar_global_read(rebound, "v", 4, 11) is None
