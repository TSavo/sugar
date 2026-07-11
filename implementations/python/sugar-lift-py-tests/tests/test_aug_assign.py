"""Augmented assignment is a rebind over the old binding: `x += v` reads the
old x (definition-scope law), asks the floor verb, and rebinds the name.
Each op is its own sugar -- no string-fork dispatch. The statement is support
(scope only)."""

from __future__ import annotations

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue


def test_add_assign_folds() -> None:
    record = compose_block("    x = 1\n    x += 2\n    return x\n")
    assert record == BlockValue((ReturnValue(TermValue(3)),))


def test_sub_assign_folds() -> None:
    record = compose_block("    x = 5\n    x -= 2\n    return x\n")
    assert record == BlockValue((ReturnValue(TermValue(3)),))


def test_mult_assign_folds() -> None:
    record = compose_block("    x = 2\n    x *= 3\n    return x\n")
    assert record == BlockValue((ReturnValue(TermValue(6)),))


def test_div_assign_folds() -> None:
    record = compose_block("    x = 6\n    x /= 2\n    return x\n")
    assert record == BlockValue((ReturnValue(TermValue(3.0)),)) or record == BlockValue(
        (ReturnValue(TermValue(3)),)
    )


def test_mod_assign_folds() -> None:
    record = compose_block("    x = 7\n    x %= 3\n    return x\n")
    assert record == BlockValue((ReturnValue(TermValue(1)),))


def test_aug_assign_statement_contributes_nothing_to_the_record() -> None:
    record = compose_block("    x = 1\n    x += 2\n    return x\n")
    assert len(record.statements) == 1


def test_add_assign_on_unbound_name_panics() -> None:
    with pytest.raises(FactoryPanic):
        compose_block("    x += 2\n    return x\n")


def test_unowned_matmult_assign_is_loud_factory_gap() -> None:
    with pytest.raises(FactoryPanic):
        compose_block("    x = 1\n    x @= 2\n    return x\n")
