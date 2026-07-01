"""AddSugar is a leaf BODY sugar on the array-map path: it reduces `x + n` to the
concrete sum when `x` is a bound element. Supporting `*`, `[]`, string concat, ...
is MORE SUGAR (more leaf bodies), never a smarter Map or Lambda."""

from __future__ import annotations

from factory_reduce import array_map_reduce

from sugar_lift_py_tests.floor import TermValue


def test_add_reduces_bound_element_plus_addend():
    assert array_map_reduce("x + 1", {"x": TermValue(5)}) == TermValue(6)
    assert array_map_reduce("x + 0", {"x": TermValue(9)}) == TermValue(9)
    assert array_map_reduce("x + 10", {"x": TermValue(2)}) == TermValue(12)
