"""OrdByteSugar lifts `ord(source[index])` as a TERM: value's byte at a fixed
position, a free bv32 var the encoder universe (str.eq-bv-blocks) constrains. It is the
rhs of `b0 = ord(value[0])`, recomposed through the BoundVar when a later expression
references b0."""
from __future__ import annotations

from factory_reduce import reduce_value

from sugar_lift_py_tests.floor import Bv32Value
from sugar_lift_py_tests.ir import make_var


def test_symbolic_ord_call_is_a_free_byte_var():
    # named by source+index so the same byte is the same var; str.eq-bv-blocks reads
    # the bytes in index order.
    assert reduce_value("ord(value[0])") == Bv32Value(make_var("byte_value_0"))
    assert reduce_value("ord(value[2])") == Bv32Value(make_var("byte_value_2"))
