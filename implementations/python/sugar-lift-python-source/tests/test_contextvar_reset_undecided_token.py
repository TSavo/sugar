"""``var.reset(token)`` with a token the lift did not see ``var.set`` mint.

CPython raises ``TypeError`` for a non-Token, ``ValueError`` for a token from
another ContextVar or Context, ``RuntimeError`` for one already used.  When
the token is an opaque value (numpy's ``printoptions`` resets with the result
of an unprojected ``_set_printoptions(...)``), the reset completes with
``None`` only under ``python:contextvar_reset.completes(...)`` and halts with
an ``UndeterminedRaiseEffect`` (owner ``ContextVarReset:<name>``) under the
complement.  It used to crash on an unbound ``ctx``.
"""

from __future__ import annotations

from types import SimpleNamespace

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.language_owned_contextvar import (
    LanguageOwnedContextVarToken,
    LanguageOwnedContextVarValue,
)
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    Halted,
    complement_guard,
    outcome_to_exitset,
)


def _reset(token, blame="reset-site"):
    variable = LanguageOwnedContextVarValue(name="v", has_default=True)
    return variable.call_method_with(
        SimpleNamespace(name="reset", arguments=(token,), keyword_names=(), blame=blame),
        None,
    )


def test_an_opaque_token_resets_or_raises():
    exits = outcome_to_exitset(_reset(SymbolicValue(make_var("t")))).exits
    (done,) = [face for face in exits if isinstance(face, Completed)]
    (halt,) = [face for face in exits if isinstance(face, Halted)]
    assert done.value == NoneValue()
    assert "python:contextvar_reset.completes" in str(done.guard)
    assert halt.guard == complement_guard(done.guard)
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "ContextVarReset:v"


def test_two_resets_are_two_unknowns():
    first = outcome_to_exitset(_reset(SymbolicValue(make_var("t")), "a")).exits
    second = outcome_to_exitset(_reset(SymbolicValue(make_var("t")), "b")).exits
    assert first[0].guard != second[0].guard


def test_the_token_set_minted_still_resets_to_none():
    token = LanguageOwnedContextVarToken(variable_name="v", occurrence="set.py:1:0")
    assert _reset(token) == Complete(NoneValue())
