"""RED laws for CPython enum._is_descriptor over source function objects."""

from dataclasses import dataclass

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.callable_application import CallableApplication
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import (
    BuiltinSemanticCallable,
    CallSiteValue,
    ObjectMethodValue,
    StringValue,
    TermValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


def _source_method() -> ObjectMethodValue:
    source = (
        "class Roster:\n"
        "    def member(self):\n"
        "        return 1\n"
    )
    tree = SourceFile((source, "descriptor.py", blake3_512_of(source.encode())))
    definition_node = next(
        node for node in tree.root.body if isinstance(node, ClassDef)
    )
    definition = definition_node.sugar().desugar(
        ReduceContext.root(owner="descriptor-red")
    ).value
    method = definition.namespace_members_in_source_order()[0][2]
    assert isinstance(method, ObjectMethodValue)
    assert method.source_call_frame_cid
    return method


def _hasattr(value, name):
    return BuiltinSemanticCallable("python.hasattr").callable_application_with(
        CallableApplication(
            (value, StringValue(name)),
            (),
            "descriptor.py:6:11",
        ),
        ReduceContext.root(owner="descriptor-red"),
    )


def test_builtin_temporal_authenticates_hasattr_before_named_call_dispatch():
    """RED: bare ``hasattr`` currently has no authenticated builtin binding."""
    assert isinstance(
        builtin_name_temporal().value_if_bound("hasattr"), BuiltinSemanticCallable
    )


@pytest.mark.parametrize(
    ("name", "expected_type"),
    (
        ("__get__", TrueBoolLiteralSugar),
        ("__set__", FalseBoolLiteralSugar),
        ("__delete__", FalseBoolLiteralSugar),
    ),
)
def test_source_function_descriptor_contract_decides_enum_hasattr(name, expected_type):
    """RED: authority is the authenticated function object, never its spelling."""
    outcome = _hasattr(_source_method(), name)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, expected_type)


def test_non_method_value_does_not_gain_descriptor_authority():
    with pytest.raises(ConstructionPanic):
        _hasattr(TermValue(7), "__get__")


@dataclass(frozen=True)
class _FixedSugar(ConstructedTermSugar):
    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)

    def to_term(self, *, owner: str):
        return self.value.to_term(owner=owner)


def test_shadowing_hasattr_cannot_inherit_builtin_descriptor_semantics():
    context = ReduceContext.root(owner="descriptor-red")
    context = context.with_temporal(
        context.temporal.bind_value("hasattr", TermValue(7))
    )

    outcome = CallSiteSugar(
        "hasattr",
        (_FixedSugar(_source_method()), _FixedSugar(StringValue("__get__"))),
        "descriptor.py:6:11",
    ).desugar(context)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
