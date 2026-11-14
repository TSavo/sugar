"""``is`` asks object identity; equal contents never answer it.

``[] is []`` is False and ``b = a; a is b`` is True although both pairs hold
equal values, so a reduced container or instance value cannot decide ``is``
by its value term.  Two different creation sites are two objects (False); a
value of another runtime type is never the same object (False); anything
else is this comparison's own undecided identity, never equality of
contents.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor.predicate_value import PredicateValue
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

from frame_fresh import fresh
from test_builtin_container_mutation import _only_return, _returns


def _undecided(value):
    """An identity atom over this comparison's own operands, not their contents."""
    assert type(value) is PredicateValue
    formula = value.formula
    assert formula.name == "identity"
    left, right = formula.args
    assert left.name == right.name == "python:object_at"
    assert left != right
    return True


def test_two_empty_list_displays_are_two_objects(tmp_path):
    value = _only_return(tmp_path, "def f():\n    return [] is []\n")
    assert type(value) is FalseBoolLiteralSugar


def test_two_names_bound_to_two_displays_are_two_objects(tmp_path):
    source = "def f():\n    a = []\n    b = []\n    return a is b\n"
    assert type(_only_return(tmp_path, source)) is FalseBoolLiteralSugar


def test_is_not_between_two_dict_displays_is_true(tmp_path):
    source = "def f():\n    a = {}\n    return a is not {}\n"
    assert type(_only_return(tmp_path, source)) is TrueBoolLiteralSugar


def test_a_list_is_not_none(tmp_path):
    source = "def f():\n    a = []\n    return a is None\n"
    assert type(_only_return(tmp_path, source)) is FalseBoolLiteralSugar


def test_an_alias_is_never_decided_false(tmp_path):
    source = "def f():\n    a = []\n    b = a\n    a.append(1)\n    return a is b\n"
    assert _undecided(_only_return(tmp_path, source))


def test_two_constructions_of_one_class_are_not_one_object_by_contents(tmp_path):
    source = "class C:\n    pass\ndef f():\n    return C() is C()\n"
    assert _undecided(_only_return(tmp_path, source))


def test_one_display_evaluated_by_two_iterations_is_two_objects(tmp_path):
    source = (
        "def f():\n"
        "    prev = None\n"
        "    for i in (1, 2):\n"
        "        cur = []\n"
        "        if i == 2:\n"
        "            return prev is cur\n"
        "        prev = cur\n"
        "    return None\n"
    )
    assert _undecided(_only_return(tmp_path, source))


def test_two_calls_of_a_helper_returning_a_display_are_not_one_object(tmp_path):
    source = "def g():\n    return []\ndef f():\n    return g() is g()\n"
    assert _undecided(_only_return(tmp_path, source))


def test_two_appended_displays_are_not_one_object(tmp_path):
    source = (
        "def f():\n"
        "    r = []\n"
        "    for i in (1, 2):\n"
        "        r.append([])\n"
        "    return r[0] is r[1]\n"
    )
    assert _undecided(_only_return(tmp_path, source))


# -- A builtin constructor over a container makes a new object (#7757) ------
#
# ``dict(d)`` handed back ``d`` itself: ``e = dict(d)`` named the same object
# as ``d``, so ``e is d`` could not be decided False.  CPython allocates a
# new dict and copies the entries (shallow).  ``tuple(t)`` of an exact tuple
# is the one constructor CPython answers with its operand itself.

_COPIED = "def f(x):\n    d = {'a': x}\n    e = dict(d)\n"


def test_a_dict_copy_is_not_the_dict(tmp_path):
    (value,) = _returns(tmp_path, _COPIED + "    return e is d\n")[0]
    assert type(value) is FalseBoolLiteralSugar


def test_a_store_into_a_dict_copy_leaves_the_dict(tmp_path):
    from sugar_lift_py_tests.floor import DictValue, StringValue

    (value,) = _returns(tmp_path, _COPIED + "    e['k'] = 1\n    return d\n")[0]
    assert type(value) is DictValue
    assert [key for key, _ in value.entries] == [StringValue("a")]


def test_a_tuple_of_a_tuple_is_the_tuple(tmp_path):
    # CPython hands an exact tuple back as itself: one object, decided.
    source = "def f(x):\n    t = (x, 1)\n    return tuple(t) is t\n"
    (value,) = _returns(tmp_path, source)[0]
    assert type(value) is TrueBoolLiteralSugar


def _construct(operation_name, source):
    from types import SimpleNamespace

    from sugar_lift_py_tests.floor.builtin_semantic_callable import (
        BuiltinSemanticCallable,
    )

    callable_ = BuiltinSemanticCallable(operation_name)
    operation = SimpleNamespace(
        arguments=(source,), keyword_names=(), site="construct-site"
    )
    if operation_name == "python.dict.construct":
        return callable_._construct_dict(operation)
    return callable_._construct_tuple(operation)


def test_dict_of_a_current_dict_is_a_new_object_made_at_the_call():
    from sugar_lift_py_tests.floor import DictValue, StringValue, TermValue

    entries = ((StringValue("k"), TermValue(1)),)
    d = DictValue(entries, allocation="display-site")
    made = _construct("python.dict.construct", d).completed_value()
    assert made is not d
    assert type(made) is DictValue
    assert made.entries == entries
    assert made.allocation == "construct-site"


def test_dict_of_a_stale_dict_makes_nothing_current():
    from sugar_lift_py_tests.floor import DictValue, StringValue, TermValue

    stale = DictValue(((StringValue("k"), TermValue(1)),), allocation=None)
    assert _construct("python.dict.construct", stale) is None


def test_tuple_of_an_exact_tuple_is_the_same_object():
    from sugar_lift_py_tests.floor import TermValue, TupleValue

    t = TupleValue((TermValue(1),))
    assert _construct("python.tuple.construct", t).completed_value() is t


# -- Immutable values answer ``is`` by the same object rule (#7757) --------
#
# ``TupleValue``, ``StringValue``, ``BytesValue`` and ``TermValue`` answered
# ``is`` with ``identity`` over their value terms, so ``(x,) is (x,)`` was
# the reflexive identity (True) although CPython builds two tuples.  Equal
# values never decide one object: CPython's interning and constant merging
# are implementation-defined.  Different values, or types, are two objects.


def test_two_tuple_displays_reading_a_variable_are_two_objects(tmp_path):
    (value,) = _returns(tmp_path, "def f(x):\n    return (x,) is (x,)\n")[0]
    assert type(value) is FalseBoolLiteralSugar


def test_one_tuple_display_read_twice_is_one_object(tmp_path):
    source = "def f(x):\n    t = (x,)\n    return t is t\n"
    (value,) = _returns(tmp_path, source)[0]
    assert type(value) is TrueBoolLiteralSugar


def test_an_alias_of_a_tuple_is_the_tuple(tmp_path):
    source = "def f(x):\n    t = (x, 1)\n    u = t\n    return u is t\n"
    (value,) = _returns(tmp_path, source)[0]
    assert type(value) is TrueBoolLiteralSugar


def test_an_alias_of_a_list_display_is_the_list(tmp_path):
    source = "def f():\n    a = []\n    b = a\n    return a is b\n"
    assert type(_only_return(tmp_path, source)) is TrueBoolLiteralSugar


def test_two_constant_tuples_may_be_one_merged_constant(tmp_path):
    source = "def f():\n    a = (1, 2)\n    b = (1, 2)\n    return a is b\n"
    assert _undecided(_only_return(tmp_path, source))


def test_two_constant_tuples_of_different_values_are_two_objects(tmp_path):
    source = "def f():\n    a = (1, 2)\n    b = (1, 3)\n    return a is b\n"
    assert type(_only_return(tmp_path, source)) is FalseBoolLiteralSugar


def test_equal_ints_are_not_decided_one_object(tmp_path):
    source = "def f():\n    a = 1000\n    b = 1000\n    return a is b\n"
    assert _undecided(_only_return(tmp_path, source))


def test_different_ints_are_two_objects(tmp_path):
    source = "def f():\n    a = 1\n    b = 2\n    return a is b\n"
    assert type(_only_return(tmp_path, source)) is FalseBoolLiteralSugar


def test_an_int_and_a_float_are_two_objects(tmp_path):
    source = "def f():\n    a = 1\n    b = 1.0\n    return a is b\n"
    assert type(_only_return(tmp_path, source)) is FalseBoolLiteralSugar


def test_equal_strings_are_not_decided_one_object(tmp_path):
    source = "def f():\n    a = 'a'\n    b = 'a'\n    return a is b\n"
    assert _undecided(_only_return(tmp_path, source))


def test_different_strings_are_two_objects(tmp_path):
    source = "def f():\n    a = 'a'\n    b = 'b'\n    return a is b\n"
    assert type(_only_return(tmp_path, source)) is FalseBoolLiteralSugar


def test_equal_bytes_are_not_decided_one_object(tmp_path):
    source = "def f():\n    a = b'a'\n    b = b'a'\n    return a is b\n"
    assert _undecided(_only_return(tmp_path, source))


def test_a_string_is_not_none(tmp_path):
    source = "def f():\n    a = 'a'\n    return a is None\n"
    assert type(_only_return(tmp_path, source)) is FalseBoolLiteralSugar


def test_none_and_the_bools_are_singletons(tmp_path):
    for literal in ("None", "True", "False"):
        source = f"def f():\n    a = {literal}\n    b = {literal}\n    return a is b\n"
        assert type(_only_return(tmp_path / literal, source)) is TrueBoolLiteralSugar


def test_an_int_is_not_true(tmp_path):
    source = "def f():\n    a = 1\n    return a is True\n"
    assert type(_only_return(tmp_path, source)) is FalseBoolLiteralSugar


def test_a_tuple_of_one_construction_is_itself():
    from sugar_lift_py_tests.floor import TermValue, TupleValue

    t = TupleValue((TermValue(1),), allocation="display-site")
    assert type(t.is_identical(t, "is-site").completed_value()) is (
        TrueBoolLiteralSugar
    )


def test_tuples_of_two_constructions_are_two_objects():
    from sugar_lift_py_tests.floor import TermValue, TupleValue

    left = TupleValue((TermValue(1),), allocation="one-site")
    right = TupleValue((TermValue(1),), allocation="other-site")
    assert type(left.is_identical(right, "is-site").completed_value()) is (
        FalseBoolLiteralSugar
    )


def test_an_arrived_tuple_names_no_construction():
    from sugar_lift_py_tests.floor import TermValue, TupleValue
    from sugar_lift_py_tests.floor.object_identity import arrived

    t = TupleValue((TermValue(1),), allocation="display-site")
    assert arrived(t, "binding-read").allocation is None
    assert arrived(t, "binding-read") == t


def test_a_formal_after_its_own_mutation_is_itself(tmp_path):
    # A formal is the caller's object: its identity with itself stays one term.
    # The formal's method waits for the caller's actual (``method_call``).
    from test_assignment_evaluates_rhs import _rows
    from test_formal_method_call_defers import _carrier, _discharge
    from sugar_lift_py_tests.floor import ListValue

    source = "def f(a):\n    a.append(1)\n    return a is a\n"
    exits = _discharge(_carrier(tmp_path, source), fresh(ListValue, ()))
    (value,) = [payload for kind, payload, _ in _rows(exits) if kind == "return"]
    assert type(value) is PredicateValue
    left, right = value.formula.args
    assert left == right
