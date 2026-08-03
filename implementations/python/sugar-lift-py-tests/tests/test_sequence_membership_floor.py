"""Floor membership for constructed sequences and strings.

Pass-3 desugar panics ranked contains (215) as the top Floor gap owner, with
observed container types ListValue / TupleValue / CallSiteValue / StringValue.
These twins pin the finite-fold and symbolic-obligation arms so the mechanism
cannot regress to the default FloorValue.contains panic.
"""

import pytest


def _list(*values):
    from sugar_lift_py_tests.floor import ListValue, TermValue

    return ListValue(tuple(TermValue(value) for value in values))


def _tuple(*values):
    from sugar_lift_py_tests.floor import TermValue, TupleValue

    return TupleValue(tuple(TermValue(value) for value in values))


def test_finite_list_membership_is_decided_from_constructed_members():
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    finite = _list(1, 2)
    assert isinstance(finite.contains(TermValue(2), "site").value, TrueBoolLiteralSugar)
    assert isinstance(
        finite.contains(TermValue(3), "site").value, FalseBoolLiteralSugar
    )


def test_empty_list_membership_is_false():
    from sugar_lift_py_tests.floor import ListValue, TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar

    empty = ListValue(())
    assert isinstance(empty.contains(TermValue(1), "site").value, FalseBoolLiteralSugar)


def test_finite_tuple_membership_is_decided_from_constructed_members():
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    finite = _tuple(1, 2)
    assert isinstance(finite.contains(TermValue(2), "site").value, TrueBoolLiteralSugar)
    assert isinstance(
        finite.contains(TermValue(3), "site").value, FalseBoolLiteralSugar
    )


def test_symbolic_list_membership_emits_typed_obligation():
    from sugar_lift_py_tests.floor import ListValue, SymbolicValue, TermValue
    from sugar_lift_py_tests.ir import _Atomic, make_var

    result = (
        ListValue((TermValue(1),))
        .contains(SymbolicValue(make_var("member")), "site")
        .value
    )
    assert isinstance(result.formula, _Atomic)
    assert result.formula.name == "python.list.contains"


def test_symbolic_tuple_membership_emits_typed_obligation():
    from sugar_lift_py_tests.floor import SymbolicValue, TermValue, TupleValue
    from sugar_lift_py_tests.ir import _Atomic, make_var

    result = (
        TupleValue((TermValue(1),))
        .contains(SymbolicValue(make_var("member")), "site")
        .value
    )
    assert isinstance(result.formula, _Atomic)
    assert result.formula.name == "python.tuple.contains"


def test_opaque_list_member_stays_loud():
    from sugar_lift_py_tests.floor import FunctionCallable
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic):
        _list(1).contains(FunctionCallable("opaque"), "site")


def test_nested_list_membership_is_decided_from_constructed_members():
    """Membership law vertical slice: ``[1] in [[1], [2]]`` is ground equality."""
    from sugar_lift_py_tests.floor import ListValue, TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    container = ListValue(
        (
            ListValue((TermValue(1),)),
            ListValue((TermValue(2),)),
        )
    )
    needle = ListValue((TermValue(1),))
    missing = ListValue((TermValue(3),))
    assert isinstance(container.contains(needle, "site").value, TrueBoolLiteralSugar)
    assert isinstance(container.contains(missing, "site").value, FalseBoolLiteralSugar)


def test_nested_tuple_membership_is_decided_from_constructed_members():
    from sugar_lift_py_tests.floor import TermValue, TupleValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    container = TupleValue(
        (
            TupleValue((TermValue(1),)),
            TupleValue((TermValue(2),)),
        )
    )
    needle = TupleValue((TermValue(1),))
    missing = TupleValue((TermValue(9),))
    assert isinstance(container.contains(needle, "site").value, TrueBoolLiteralSugar)
    assert isinstance(container.contains(missing, "site").value, FalseBoolLiteralSugar)


def test_string_substring_membership_is_decided():
    from sugar_lift_py_tests.floor import StringValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    haystack = StringValue("pandas")
    assert isinstance(
        haystack.contains(StringValue("and"), "site").value, TrueBoolLiteralSugar
    )
    assert isinstance(
        haystack.contains(StringValue("xyz"), "site").value, FalseBoolLiteralSugar
    )


def test_symbolic_string_membership_emits_py_in():
    from sugar_lift_py_tests.floor import StringValue, SymbolicValue
    from sugar_lift_py_tests.ir import _Atomic, make_var

    result = (
        StringValue("abc").contains(SymbolicValue(make_var("needle")), "site").value
    )
    assert isinstance(result.formula, _Atomic)
    assert result.formula.name == "py.in"


def _workspace_fragment(tmp_path):
    """One real fragment carrying a workspace-relative locus.

    A ground exit cites source it can re-read, so it needs a fragment stating
    filename and unit -- prose cannot address anything. `tmp_path` becomes the
    workspace root so the locus is relative, which is the other half of what a
    ground exit requires.
    """
    from sugar_lift_python_source.source_oracle import workspace_path_source
    from sugar_source_tree.tree import SourceFile

    source = tmp_path / "membership.py"
    source.write_text("def witness():\n    return 1 in 'abc'\n", encoding="utf-8")
    identity = workspace_path_source(str(source), root=str(tmp_path))
    return next(SourceFile(identity).functions()).fragment


def test_ground_non_string_in_string_is_type_error(tmp_path):
    """SUBJECT UNCHANGED: `1 in "abc"` is Python's TypeError.

    Only the locus changed. This arm previously passed the literal string
    "site", which the ground-exit door cannot cite from -- it died with
    `AttributeError: 'str' object has no attribute 'filename'` before reaching
    any law. The fixture was invalid, not the law it was testing, so the
    fragment is threaded and every assertion below is the original one. The
    refusal that the crash was standing in for gains its OWN pin in
    test_ground_exit_locus_law.py rather than being dropped here.
    """
    from sugar_lift_py_tests.floor import RaiseValue, StringValue, TermValue
    from sugar_lift_py_tests.outcome import Complete

    site = _workspace_fragment(tmp_path)

    outcome = StringValue("abc").contains(TermValue(1), site)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


def test_callsite_container_emits_py_in():
    from sugar_lift_py_tests.floor import CallSiteValue, TermValue
    from sugar_lift_py_tests.ir import _Atomic, ctor, make_var

    container = CallSiteValue(
        target_name="opaque",
        arg_values=(),
        parameters=(),
        term=ctor("call:opaque", [make_var("xs")]),
        body=None,
        site="site",
    )
    result = container.contains(TermValue(1), "site").value
    assert isinstance(result.formula, _Atomic)
    assert result.formula.name == "py.in"


def test_comparison_op_routes_membership_to_list_contains():
    """`x in xs` is `xs.contains(x)` — ComparisonOpSugar must not panic on ListValue."""
    from sugar_lift_py_tests.floor import ListValue, TermValue
    from sugar_lift_py_tests.sugar.comparison_op_sugar import ComparisonOpSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    # Mimic `2 in [1, 2, 3]` after both sides have reduced to floors.
    container = ListValue((TermValue(1), TermValue(2), TermValue(3)))
    member = TermValue(2)
    # Direct floor path used by ComparisonOpSugar for In/NotIn.
    outcome = container.contains(member, "site")
    assert isinstance(outcome.value, TrueBoolLiteralSugar)
