"""AttributeSugar lowers Python attribute access to the `py.attr` ctor."""
from __future__ import annotations

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.ir import ctor, make_var, str_const


def test_attribute_reduces_to_py_attr_ctor() -> None:
    assert fol(reduce_term("arr.shape")) == fol(
        ctor("py.attr", [make_var("arr"), str_const("shape")])
    )


def test_call_result_attribute_reduces_to_py_attr_ctor() -> None:
    assert fol(reduce_term("np.any(arr).dtype")) == fol(
        ctor(
            "py.attr",
            [
                ctor("call:any", [make_var("arr")]),
                str_const("dtype"),
            ],
        )
    )
