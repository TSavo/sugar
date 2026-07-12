from __future__ import annotations

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.factory import FactoryPanic
from sugar_lift_py_tests.floor import ListValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, make_var, num


def test_list_add_concatenates_constructed_elements() -> None:
    assert reduce_value("[1, 2] + [3]") == ListValue(
        (TermValue(1), TermValue(2), TermValue(3))
    )


def test_list_add_with_runtime_peer_cites_the_existing_operation_coordinate() -> None:
    value = reduce_value(
        "[1, 2] + tail", binds={"tail": SymbolicValue(make_var("tail"))}
    )

    assert value == SymbolicValue(
        ctor("+", [ctor("array", [num(1), num(2)]), make_var("tail")])
    )


def test_statically_invalid_list_addition_remains_loud() -> None:
    with pytest.raises(FactoryPanic, match="stand on the addition floor"):
        ListValue((TermValue(1),)).add(TermValue(2), "t.py:1:0")


def test_list_value_declares_its_add_floor_structurally() -> None:
    assert "add" in ListValue.__dict__
