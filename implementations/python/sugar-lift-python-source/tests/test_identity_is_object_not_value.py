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
from test_builtin_container_mutation import _only_return


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
