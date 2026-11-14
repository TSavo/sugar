"""``x in c`` on a built-in container is CPython's ``is``-or-``==`` lookup.

``1 in {True}`` lifted as False: membership compared a bool and an int as two
unrelated literal kinds, so every bool/int pair (``True in [1]``,
``0 in (False,)``, ``True in {1: 2}``, ``(1, True) in [(1, 1)]``) decided the
wrong arm -- and ``{1: 'a'}[1.0]`` was a KeyError.

One law now answers list/tuple/set/dict membership, a dict's key lookup and
the cited mutating methods (``floor/membership.py``): a member matches when
``x is e or x == e``; ``bool`` compares as its ``int`` and ``1.0 == 1``; two
NaNs are undecided (identity, which the floor does not carry, decides); a
set/dict hashes first, so a decided unhashable needle is ``TypeError``; an
undecided member comparison stays the typed ``python.<kind>.contains``
obligation, never False.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import DictValue, StringValue, TermValue, TupleValue
from sugar_lift_py_tests.floor.membership import member_equal, position
from sugar_lift_py_tests.floor.predicate_value import PredicateValue
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

from frame_fresh import fresh
from test_builtin_container_mutation import _only_return, _returns


def _value(tmp_path, expression):
    return _only_return(tmp_path, f"def f(x):\n    return {expression}\n")


@pytest.mark.parametrize(
    "expression",
    [
        "1 in {True}",
        "True in [1]",
        "0 in (False,)",
        "True in {1: 2}",
        "1.0 in [1]",
        "1 in {1.0: 2}",
        "(1, True) in [(1, 1)]",
        "3 not in {True}",
    ],
)
def test_a_bool_or_float_member_is_the_equal_int(tmp_path, expression):
    assert type(_value(tmp_path, expression)) is TrueBoolLiteralSugar


@pytest.mark.parametrize("expression", ["2 in {True}", "1 in {}", "'1' in [1]"])
def test_an_unequal_member_is_absent(tmp_path, expression):
    assert type(_value(tmp_path, expression)) is FalseBoolLiteralSugar


def test_an_undecided_member_is_an_obligation_not_false(tmp_path):
    value = _value(tmp_path, "1 in [x]")
    assert type(value) is PredicateValue
    assert value.formula.name == "python.list.contains"


def test_a_decided_unequal_tuple_element_decides_even_beside_an_unknown(tmp_path):
    # ``(1, x) == (2, 3)`` is False at its first element, whatever ``x`` is.
    assert type(_value(tmp_path, "(1, x) in [(2, 3)]")) is FalseBoolLiteralSugar


@pytest.mark.parametrize("expression", ["[1] in {1}", "([1],) in {1}", "[1] in {}"])
def test_an_unhashable_needle_in_a_set_or_dict_is_type_error(tmp_path, expression):
    returns, halts = _returns(tmp_path, f"def f(x):\n    return {expression}\n")
    assert returns == []
    assert [halt.exception_name for halt in halts] == ["TypeError"]


def test_nan_membership_is_undecided_by_identity_and_false_by_value(tmp_path):
    value = _only_return(
        tmp_path,
        "def f():\n    n = 1e999 - 1e999\n    return (n in [n], n in [1.0])\n",
    )
    same, other = value.elements
    assert type(same) is PredicateValue
    assert type(other) is FalseBoolLiteralSugar


def test_one_equality_answers_the_shared_lookup():
    nan = TermValue(float("nan"))
    assert member_equal(TrueBoolLiteralSugar(site=None), TermValue(1)) is True
    assert member_equal(FalseBoolLiteralSugar(site=None), TermValue(0.0)) is True
    assert member_equal(TrueBoolLiteralSugar(site=None), TermValue(2)) is False
    assert member_equal(nan, nan) is None
    assert member_equal(nan, TermValue(1.0)) is False
    assert position(TermValue(1), (TermValue(0), TrueBoolLiteralSugar(site=None))) == 1


@pytest.mark.parametrize(
    "expression", ["{1: 'a'}[True]", "{1: 'a'}[1.0]", "{True: 'a'}[1]"]
)
def test_a_dict_subscript_finds_the_equal_key(tmp_path, expression):
    assert _value(tmp_path, expression) == StringValue("a")


def test_a_store_under_an_equal_key_keeps_the_stored_key(tmp_path):
    source = 'def f():\n    d = {1: "a"}\n    d[True] = "b"\n    return d\n'
    assert _only_return(tmp_path, source) == fresh(
        DictValue, ((TermValue(1), StringValue("b")),)
    )


def test_set_add_of_an_equal_float_keeps_one_member(tmp_path):
    source = "def f():\n    s = {1}\n    s.add(1.0)\n    s.add(True)\n    return len(s)\n"
    assert _only_return(tmp_path, source) == TermValue(1)


@pytest.mark.parametrize(
    "expression", ["None in [g()]", "[1] in [g()]", "(1,) in (g(),)"]
)
def test_none_or_a_display_against_a_call_result_is_never_false(tmp_path, expression):
    # ``None == g()`` and ``[1] == g()`` depend on what ``g`` returns: the
    # member comparison is undecided, so membership is never decided False.
    # ``h`` is unbound, so ``g()`` may raise too: its one halt is that call's.
    source = f"def g():\n    return h()\ndef f():\n    return {expression}\n"
    (value,), halts = _returns(tmp_path, source)
    assert [halt.producer_node_owner for halt in halts] == ["UnknownCallee:h"]
    assert type(value) is not FalseBoolLiteralSugar
    assert type(value) is not TrueBoolLiteralSugar


@pytest.mark.parametrize("expression", ["None in [0]", "[1] in [(1,)]", "{1} in [[1]]"])
def test_decided_builtins_of_different_types_are_unequal(tmp_path, expression):
    assert type(_value(tmp_path, expression)) is FalseBoolLiteralSugar
