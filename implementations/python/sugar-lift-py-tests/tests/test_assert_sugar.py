"""AssertSugar: reduce the condition, and the result states itself. A symbolic
predicate states an inv -- the fact the record emits (first encounter: a fact
to discharge; a later consumer meets it as a warrant, a constraint -- that
duality is protocol position, never the sugar's). Ground True states nothing
(support). Ground False is lift-time decidable and panics rather than minting
a runtime effect. A value that cannot stand as a statable fact also panics."""

from __future__ import annotations

import pytest
from factory_reduce import compose_block

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import BlockValue, InvValue, ReturnValue, TermValue
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import make_var, num, py_eq


def test_symbolic_assert_states_an_inv() -> None:
    block = compose_block(
        "    assert z == 1\n    return 2\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    assert block == BlockValue(
        (InvValue(py_eq(make_var("z"), num(1))), ReturnValue(TermValue(2)))
    )


def test_ground_true_assert_states_nothing() -> None:
    assert compose_block("    assert 1 == 1\n    return 2\n") == BlockValue(
        (ReturnValue(TermValue(2)),)
    )


def test_ground_false_assert_wrong_twin_panics() -> None:
    with pytest.raises(FactoryPanic):
        compose_block("    assert 1 == 2\n    return 2\n")


def test_assert_nonzero_folds_through_truth_to_support() -> None:
    # `assert 5` is Python truthiness: TermValue.truth folds True, stated is support.
    assert compose_block("    assert 5\n    return 2\n") == BlockValue(
        (ReturnValue(TermValue(2)),)
    )


def test_runtime_expression_assert_message_does_not_emit_conditional_effect() -> None:
    """#4594: message evaluation is diagnostic-only, never a py.* effect.

    `assert <true>, f(y)` must not invent a conditional effect from the
    message Call. On the holding path the message is unevaluated at runtime;
    at lift it is provenance spelling only. Ground-false remains a loud panic.
    """
    holding = compose_block("    assert 1 == 1, f(y)\n    return 2\n")
    assert holding == BlockValue((ReturnValue(TermValue(2)),))

    with pytest.raises(FactoryPanic):
        compose_block("    assert 1 == 2, f(y)\n    return 2\n")
