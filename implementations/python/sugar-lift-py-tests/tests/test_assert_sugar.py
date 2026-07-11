"""AssertSugar: reduce the condition, and the result states itself. A symbolic
predicate states an inv -- the fact the record emits (first encounter: a fact
to discharge; a later consumer meets it as a warrant, a constraint -- that
duality is protocol position, never the sugar's). Ground True states nothing
(support). Ground False is a recognized fact the program halts: a named
runtime effect, per the gap/fact discriminator. A value that cannot stand as
a statable fact panics."""

from __future__ import annotations

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.effect import AssertionFailedRuntimeEffect
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import BlockValue, InvValue, ReturnValue, TermValue
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import make_var, num, py_eq
from sugar_lift_py_tests.outcome import Incomplete


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


def test_ground_false_assert_is_the_named_halt() -> None:
    # The halt sits in the record (the os.exit shape): the effect entry is the
    # Incomplete, and the unreached tail stays raw, unreduced sugar.
    record = compose_block("    assert 1 == 2\n    return 2\n").statements
    assert isinstance(record[0], Incomplete)
    assert isinstance(record[0].effect, AssertionFailedRuntimeEffect)
    assert len(record) == 2  # the return never ran


def test_a_value_that_cannot_state_a_fact_panics() -> None:
    # `assert 5` is Python truthiness -- a ruling that has not happened yet.
    # TermValue does not stand as a statable fact; the honest floor gap fires.
    with pytest.raises(FactoryPanic):
        compose_block("    assert 5\n    return 2\n")
