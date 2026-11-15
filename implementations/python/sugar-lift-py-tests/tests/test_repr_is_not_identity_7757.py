"""A Python ``repr`` never names a value (#7757 inventory item 27).

Each seat below once keyed, hashed or branched on how a value prints.  Each
now reads the value's typed identity: a sort's content encoding, the IR sort's
own equality, an exception class's coordinate.  Every test pairs two values
whose spelling and identity disagree, so the seat must follow identity.
"""

from __future__ import annotations

from sugar_lift_py_tests.ir import (
    PrimitiveSort,
    _Lambda,
    _intern_term,
    atomic,
    forall,
    num,
    term_intern_scope,
)
from sugar_lift_py_tests.proofir.sorts import IntSort, Sort


class _PrintsAsSort(PrimitiveSort):
    """A primitive sort whose every instance prints the same."""

    def __repr__(self) -> str:
        return "Sort"


class _PrintsLoud(str):
    """A sort name equal to its plain twin that prints differently."""

    def __repr__(self) -> str:
        return "LOUD"


def _body():
    return atomic("p", [num(1)])


def test_quantifiers_over_sorts_that_print_alike_stay_two_formulas() -> None:
    int_sort, real_sort = _PrintsAsSort("Int"), _PrintsAsSort("Real")
    assert repr(int_sort) == repr(real_sort)
    over_int = forall("x", int_sort, _body())
    over_real = forall("x", real_sort, _body())
    assert over_int != over_real
    assert len({over_int, over_real}) == 2


def test_quantifiers_over_one_sort_printed_two_ways_are_one_formula() -> None:
    masked, plain = _PrintsAsSort("Int"), PrimitiveSort("Int")
    assert repr(masked) != repr(plain)
    assert forall("x", masked, _body()) == forall("x", plain, _body())


def test_formula_intern_keeps_quantifiers_over_sorts_that_print_alike_apart() -> None:
    with term_intern_scope():
        over_int = forall("x", _PrintsAsSort("Int"), _body())
        over_real = forall("x", _PrintsAsSort("Real"), _body())
        assert over_int is not over_real
        assert over_real.sort == _PrintsAsSort("Real")


def test_term_intern_keeps_lambdas_over_sorts_that_print_alike_apart() -> None:
    with term_intern_scope():
        over_int = _intern_term(_Lambda("x", _PrintsAsSort("Int"), num(1)))
        over_real = _intern_term(_Lambda("x", _PrintsAsSort("Real"), num(1)))
        assert over_int is not over_real
        assert over_real.param_sort == _PrintsAsSort("Real")


def test_proofir_sort_hash_follows_its_equality_not_its_spelling() -> None:
    loud = Sort(name="Int", ir_sort=PrimitiveSort(_PrintsLoud("Int")))
    plain = IntSort()
    assert repr(loud.ir_sort) != repr(plain.ir_sort)
    assert loud == plain
    assert hash(loud) == hash(plain)
    assert len({loud, plain}) == 1
