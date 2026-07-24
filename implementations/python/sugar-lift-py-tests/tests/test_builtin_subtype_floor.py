from dataclasses import replace

import pytest


def _class(name, *bases):
    from sugar_lift_py_tests.floor import BlockValue, ClassValue

    return ClassValue(name=name, bases=bases, record=BlockValue(()))


def test_constructed_subtype_graph_closes_direct_transitive_and_unrelated():
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    base = _class("RenamedBase")
    middle = _class("RenamedMiddle", base)
    leaf = _class("RenamedLeaf", middle)
    unrelated = _class("RenamedOther")

    assert isinstance(leaf.test_python_subtype(base, "site"), Complete)
    assert isinstance(
        leaf.test_python_subtype(base, "site").value, TrueBoolLiteralSugar
    )
    assert isinstance(
        leaf.test_python_subtype(unrelated, "site").value, FalseBoolLiteralSugar
    )


def test_tuple_of_types_is_finite_subtype_disjunction():
    from sugar_lift_py_tests.floor import TupleValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    base = _class("Base")
    leaf = _class("Leaf", base)
    other = _class("Other")

    assert isinstance(
        leaf.test_python_subtype(TupleValue((other, base)), "site").value,
        TrueBoolLiteralSugar,
    )
    assert isinstance(
        base.test_python_subtype(TupleValue((other, leaf)), "site").value,
        FalseBoolLiteralSugar,
    )


def test_symbolic_subtype_emits_typed_obligation():
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import _Atomic, ctor, make_var

    subtype = SymbolicValue(make_var("T"))
    supertype = SymbolicValue(ctor("python:type", [make_var("U")]))
    result = subtype.test_python_subtype(supertype, "site").value

    assert isinstance(result.formula, _Atomic)
    assert result.formula.name == "python.subtype"


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
        (runtime, "python.set.contains", operands, result),
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
    assert isinstance(result.value, TrueBoolLiteralSugar)
    witness = receiver.witness_for((leaf, base), result.value)
    witness.verify(
        receiver.runtime_identity,
        receiver.operation,
        (leaf.to_term(owner="test"), base.to_term(owner="test")),
        result.value.to_term(owner="test"),
    )


def test_shadowed_issubclass_does_not_inherit_builtin_semantics():
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal

    shadowed = builtin_name_temporal().bind_value("issubclass", TermValue(7))
    assert isinstance(shadowed.value_for("issubclass"), TermValue)


def test_named_call_dispatches_through_authenticated_temporal_floor():
    from dataclasses import dataclass

    from sugar_lift_py_tests.context import FactoryBuildContext
    from sugar_lift_py_tests.claim import SugarCatalog
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
    from sugar_lift_py_tests.sugar.sugar_base import Sugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    @dataclass(frozen=True)
    class ValueSugar(Sugar):
        value: object

        @classmethod
        def witnesses(cls):
            return ()

        def desugar(self, ctx=None):
            return Complete(self.value)

    base = _class("Base")
    leaf = _class("Leaf", base)
    outcome = CallSiteSugar(
        "issubclass", (ValueSugar(leaf), ValueSugar(base)), "site"
    ).desugar(FactoryBuildContext("test.py", SugarCatalog()))

    assert isinstance(outcome.value, TrueBoolLiteralSugar)
