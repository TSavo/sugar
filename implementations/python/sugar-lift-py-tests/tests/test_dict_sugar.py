from __future__ import annotations

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.ir import ctor, num, str_const


def test_dict_literal_lifts_as_python_dict_term() -> None:
    assert fol(reduce_term('{"a": [1, 2], "b": 3}')) == fol(
        ctor(
            "python:dict",
            [
                ctor(
                    "python:dict_entry",
                    [str_const("a"), ctor("array", [num(1), num(2)])],
                ),
                ctor("python:dict_entry", [str_const("b"), num(3)]),
            ],
        )
    )


def test_dict_literal_order_and_kind_are_structural() -> None:
    first = reduce_term('{"a": 1, "b": 2}')
    second = reduce_term('{"b": 2, "a": 1}')

    assert fol(first) != fol(second)
    assert fol(first) != fol(ctor("array", [num(1), num(2)]))


def test_dict_literal_preserves_set_entry_shape() -> None:
    assert fol(reduce_term('{"bad": {1}}')) == fol(
        ctor(
            "python:dict",
            [
                ctor(
                    "python:dict_entry",
                    [str_const("bad"), ctor("python:set", [num(1)])],
                )
            ],
        )
    )
