from __future__ import annotations

from factory_reduce import reduce_value

from sugar_lift_py_tests.floor import TermValue, TupleValue


def test_tuple_add_concatenates_constructed_elements() -> None:
    assert reduce_value("(1, 2) + (3,)") == TupleValue(
        (TermValue(1), TermValue(2), TermValue(3))
    )
