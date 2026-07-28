"""GuardedValue distributes attribute and membership over both faces.

Full-dump (pandas untruncated): attribute refusals 229 with GuardedValue 197;
contains residual after sequence floors still names GuardedValue. These twins
pin the distribution law so the default FloorValue.attribute/contains panics
cannot reappear on a guarded receiver.
"""

from sugar_lift_py_tests.floor import GuardedValue, ListValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


def _guard():
    return atomic("choose", [])


def test_guarded_attribute_keeps_symbolic_face_refusal_loud():
    from sugar_source_tree.panic import SugarNotWritten

    true_face = SymbolicValue(make_var("t"))
    false_face = SymbolicValue(make_var("f"))
    guarded = GuardedValue(_guard(), true_face, false_face)
    try:
        guarded.attribute("x", "site")
    except SugarNotWritten as refusal:
        assert refusal.owner == "SymbolicValue.attribute"
        assert refusal.observed.endswith("SymbolicValue.x")
    else:
        raise AssertionError("guarded symbolic attribute invented completion")


def test_guarded_list_membership_opposite_faces_emit_predicate():
    true_face = ListValue((TermValue(1), TermValue(2)))
    false_face = ListValue((TermValue(3),))
    guarded = GuardedValue(_guard(), true_face, false_face)
    outcome = guarded.contains(TermValue(2), "site")
    assert isinstance(outcome, Complete)
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue

    # 2 ∈ true, 2 ∉ false → joined formula is the guard itself.
    assert isinstance(outcome.value, PredicateValue)
    assert outcome.value.formula == _guard()


def test_guarded_list_membership_both_true_is_decidable():
    true_face = ListValue((TermValue(1), TermValue(2)))
    false_face = ListValue((TermValue(2), TermValue(3)))
    guarded = GuardedValue(_guard(), true_face, false_face)
    outcome = guarded.contains(TermValue(2), "site")
    assert isinstance(outcome, Complete)
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue

    assert isinstance(outcome.value, (TrueBoolLiteralSugar, PredicateValue))


def test_guarded_list_membership_both_false_is_decidable():
    true_face = ListValue((TermValue(1),))
    false_face = ListValue((TermValue(3),))
    guarded = GuardedValue(_guard(), true_face, false_face)
    outcome = guarded.contains(TermValue(9), "site")
    assert isinstance(outcome, Complete)
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue

    assert isinstance(outcome.value, (FalseBoolLiteralSugar, PredicateValue))
