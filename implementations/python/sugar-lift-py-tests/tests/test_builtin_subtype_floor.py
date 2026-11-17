from dataclasses import replace

import pytest


def _class(name, *bases):
    from sugar_lift_py_tests.floor import BlockValue, ClassValue

    return ClassValue(name=name, bases=bases, record=BlockValue(()))


def test_constructed_subtype_graph_closes_direct_transitive_and_unrelated():
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    base = _class("RenamedBase")
    middle = _class("RenamedMiddle", base)
    leaf = _class("RenamedLeaf", middle)
    unrelated = _class("RenamedOther")

    assert leaf.test_python_subtype(base, "site").completed_value() is not None
    assert isinstance(
        leaf.test_python_subtype(base, "site").completed_value(), TrueBoolLiteralSugar
    )
    assert isinstance(
        leaf.test_python_subtype(unrelated, "site").completed_value(),
        FalseBoolLiteralSugar,
    )


def test_tuple_of_types_is_finite_subtype_disjunction():
    from sugar_lift_py_tests.floor import TupleValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    base = _class("Base")
    leaf = _class("Leaf", base)
    other = _class("Other")

    assert isinstance(
        leaf.test_python_subtype(TupleValue((other, base)), "site").completed_value(),
        TrueBoolLiteralSugar,
    )
    assert isinstance(
        base.test_python_subtype(TupleValue((other, leaf)), "site").completed_value(),
        FalseBoolLiteralSugar,
    )


def test_symbolic_subtype_is_the_undecided_type_test_its_halt_kept():
    """``issubclass(<undecided>, U)``: the operand may be no class (its
    ``__bases__`` read may raise; none is the ``TypeError``) and ``U``'s
    metaclass may run its own ``__subclasscheck__``.  Never a halt-free
    ``python.subtype`` completion (#7757)."""
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import ctor, make_var
    from sugar_lift_py_tests.outcome import Completed

    subtype = SymbolicValue(make_var("T"))
    supertype = SymbolicValue(ctor("python:type", [make_var("U")]))
    outcome = subtype.test_python_subtype(supertype, "site")

    assert outcome.completed_value() is None, outcome
    (completed,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert "python:issubclass_op.completes" in repr(completed.guard)
    assert "python:issubclass_result" in repr(completed.value)
    assert "python.subtype" not in repr(outcome)
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect), halt
    assert halt.effect.producer_node_owner == "SymbolicValue.test_python_subtype"
    for arm in outcome.exits:
        assert arm.owed, arm


def test_a_class_against_an_undecided_supertype_keeps_the_halt():
    """``issubclass(<builtin class>, <undecided>)``: the supertype may be no
    class, or run its metaclass's ``__subclasscheck__``."""
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var

    outcome = _class("Leaf").test_python_subtype(SymbolicValue(make_var("U")), "site")

    assert outcome.completed_value() is None, outcome
    (halt,) = outcome.halts()
    assert halt.effect.producer_node_owner == "ClassValue.test_python_subtype"


def test_non_type_supertype_stays_loud():
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic):
        _class("Leaf").test_python_subtype(TermValue(3), "site")


def test_closed_operation_witness_rejects_each_lying_coordinate():
    from sugar_lift_py_tests.floor.closed_operation_witness import (
        ClosedSemanticOperationWitness,
        PythonRuntimeIdentity,
    )
    from sugar_lift_py_tests.ir import bool_const, ctor, str_const

    runtime = PythonRuntimeIdentity.current()
    operands = (
        ctor("python:type", [str_const("Leaf")]),
        ctor("python:type", [str_const("Base")]),
    )
    result = bool_const(True)
    witness = ClosedSemanticOperationWitness.mint(
        runtime, "python.issubclass", operands, result
    )
    witness.verify(runtime, "python.issubclass", operands, result)

    lies = (
        (
            replace(runtime, minor=runtime.minor + 1),
            "python.issubclass",
            operands,
            result,
        ),
        (runtime, "python.set.union", operands, result),
        (runtime, "python.issubclass", tuple(reversed(operands)), result),
        (runtime, "python.issubclass", operands, bool_const(False)),
    )
    for lie in lies:
        with pytest.raises(ValueError, match="closed semantic operation witness"):
            witness.verify(*lie)


def test_authenticated_builtin_issubclass_callable_uses_floor_not_spelling():
    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.floor import BuiltinSemanticCallable
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
    from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal

    base = _class("Base")
    leaf = _class("Leaf", base)
    receiver = builtin_name_temporal().value_for("issubclass")

    assert isinstance(receiver, BuiltinSemanticCallable)
    result = receiver.callable_application_with(
        CallableApplication((leaf, base), (), "site"), None
    )
    assert isinstance(result.completed_value(), TrueBoolLiteralSugar)


def test_shadowed_issubclass_does_not_inherit_builtin_semantics():
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal

    shadowed = builtin_name_temporal().bind_value("issubclass", TermValue(7))
    assert isinstance(shadowed.value_for("issubclass"), TermValue)
