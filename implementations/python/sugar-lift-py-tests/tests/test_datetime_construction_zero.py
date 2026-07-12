from __future__ import annotations

from sugar_lift_py_tests.effect import TypeErrorRuntimeEffect
from sugar_lift_py_tests.floor import NoneValue, PredicateValue, TermValue
from sugar_lift_py_tests.ir import atomic, make_var, num
from sugar_lift_py_tests.lift_rpc import audit_lift_file


def test_term_adds_predicate_by_citing_the_operator_coordinate() -> None:
    predicate = PredicateValue(atomic("flag", [make_var("x")]), "t.py:1")
    outcome = TermValue(4).add(predicate, "t.py:1")
    assert outcome.value.to_term(owner="test").name == "+"
    assert outcome.value.to_term(owner="test").args[0] == num(4)


def test_none_floor_division_is_a_witnessed_type_error_boundary() -> None:
    outcome = NoneValue().floor_divide(TermValue(2), "t.py:1")
    assert isinstance(outcome.effect, TypeErrorRuntimeEffect)
    assert outcome.effect.witness is not None


def test_surviving_branch_binding_threads_past_sibling_return() -> None:
    source = (
        "def f(p):\n"
        "    if p:\n"
        "        b = 1\n"
        "    else:\n"
        "        return 0\n"
        "    return b\n"
    )
    _payload, gaps = audit_lift_file(source, "join.py", hold_panic=True)
    assert not [gap for gap in gaps if gap.info.get("observed") == "b"]


def test_class_lexical_binding_is_visible_to_method_default() -> None:
    source = (
        "class C:\n"
        "    sentinel = object()\n"
        "    def f(self, value=sentinel):\n"
        "        return value\n"
    )
    _payload, gaps = audit_lift_file(source, "class_scope.py", hold_panic=True)
    assert not [gap for gap in gaps if gap.info.get("observed") == "sentinel"]
