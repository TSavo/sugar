"""OrdByteSugar lifts `ord(source[index])` as a TERM: value's byte at a fixed
position, a free bv32 var the encoder universe (str.eq-bv-blocks) constrains. It is the
rhs of `b0 = ord(value[0])`, recomposed through the BoundVar when a later expression
references b0."""

from __future__ import annotations

from pathlib import Path

from factory_reduce import reduce_value

from sugar_lift_py_tests.floor import Bv32Value, StringValue, TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_symbolic_ord_call_is_a_free_byte_var():
    # named by source+index so the same byte is the same var; str.eq-bv-blocks reads
    # the bytes in index order.
    assert reduce_value("ord(value[0])") == Bv32Value(make_var("byte_value_0"))
    assert reduce_value("ord(value[2])") == Bv32Value(make_var("byte_value_2"))


def test_concrete_ord_call_reduces_when_source_binding_is_a_string():
    assert reduce_value("ord(value[0])", {"value": StringValue("x")}) == TermValue(120)


def test_ord_return_proves_truthful_and_lying_twins_through_cli(tmp_path: Path) -> None:
    def source(expected: int) -> str:
        return (
            "def A(s):\n"
            "    return ord(s[0])\n"
            "\n"
            "def test_a():\n"
            f"    assert A('x') == {expected}\n"
        )

    truthful = run_source_through_real_solver(tmp_path / "truthful", source(120))
    lying = run_source_through_real_solver(tmp_path / "lying", source(121))

    assert "OrdByteSugar" in truthful.selected_sugars
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
