"""Mutation is a rebind: `xs.append(v)` rebinds xs to the updated list. Concrete
history folds; the append statement contributes nothing to the block record
(scope only). Aliasing stays a loud gap -- not this PR."""

from __future__ import annotations

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import BlockValue, ListValue, ReturnValue, TermValue


def test_append_folds_history_into_returned_list() -> None:
    record = compose_block("    xs = [1]\n    xs.append(2)\n    return xs\n")
    assert record == BlockValue(
        (ReturnValue(ListValue((TermValue(1), TermValue(2)))),)
    )


def test_append_statement_contributes_nothing_to_the_record() -> None:
    record = compose_block("    xs = [1]\n    xs.append(2)\n    return xs\n")
    assert len(record.statements) == 1


def test_append_on_unbound_name_panics() -> None:
    with pytest.raises(FactoryPanic):
        compose_block("    xs.append(2)\n    return xs\n")


def test_append_on_term_value_panics() -> None:
    with pytest.raises(FactoryPanic):
        compose_block("    x = 1\n    x.append(2)\n    return x\n")


def test_two_appends_compose() -> None:
    record = compose_block(
        "    xs = [1]\n    xs.append(2)\n    xs.append(3)\n    return xs\n"
    )
    assert record == BlockValue(
        (ReturnValue(ListValue((TermValue(1), TermValue(2), TermValue(3)))),)
    )
