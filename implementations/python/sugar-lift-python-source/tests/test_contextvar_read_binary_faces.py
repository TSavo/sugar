"""A binary operation on a ``ContextVar.get()`` read is two-faced.

The read is whatever the running context holds, so its runtime type is
undecided and Python's ``__or__``/``__ror__`` selection for
``format_options.get() | new_opt`` (numpy's ``_set_printoptions``) is too.
The read now testifies that it denotes a value of undecided type, so it takes
the undecided binary law (#7642) instead of panicking as a value that never
testified.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import DictValue, StringValue, TermValue
from sugar_lift_py_tests.floor.language_owned_contextvar import (
    LanguageOwnedContextVarReadValue,
)
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted, outcome_to_exitset


def _read():
    return LanguageOwnedContextVarReadValue(
        variable_name="v", site="get-site", occurrence="get-site"
    )


def test_the_read_testifies_to_an_undecided_value():
    assert _read().denotes_value() is True
    assert _read().runtime_type_is_decided() is False


def test_or_with_a_dict_on_a_read_may_raise():
    exits = outcome_to_exitset(
        _read().bitwise_or(DictValue(((StringValue("k"), TermValue(1)),)), "or-site")
    ).exits
    (done,) = [face for face in exits if isinstance(face, Completed)]
    (halt,) = [face for face in exits if isinstance(face, Halted)]
    assert "python:binary_op.completes" in repr(done.guard)
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.effect.producer_node_owner == "UndecidedBinary:|"
