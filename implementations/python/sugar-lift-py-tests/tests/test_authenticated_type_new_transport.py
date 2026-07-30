"""Authenticated zero-argument super transports ``type.__new__`` results."""

import pytest

from sugar_lift_py_tests.floor import (
    BuiltinSuperValue,
    ClassValue,
    MappingObjectValue,
    RuntimeClassValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Complete


def _super_value():
    return BuiltinSuperValue(
        current_class=type(
            "CurrentClass",
            (),
            {"base_classes": (ClassValue(name="type", bases=(), record=None),)},
        )(),
        receiver=TermValue("metaclass"),
    )


def test_type_new_result_carries_the_exact_namespace_as_class_dict() -> None:
    namespace = MappingObjectValue(
        "Namespace",
        (),
        identity="namespace-coordinate",
        entries=((StringValue("member"), TermValue(7)),),
    )

    outcome = _super_value().call_method_value(
        "__new__",
        (
            TermValue("metaclass"),
            StringValue("Made"),
            TupleValue(()),
            namespace,
        ),
        owner="test",
        blame="new-site",
        keywords=(("**", MappingObjectValue("Kwds", (), entries=())),),
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RuntimeClassValue)
    assert outcome.value.name == "Made"
    projected = outcome.value.attribute("__dict__", "dict-site")
    assert isinstance(projected, Complete)
    assert projected.value.entries == namespace.entries


def test_type_new_refuses_a_non_mapping_namespace() -> None:
    with pytest.raises(ConstructionPanic):
        _super_value().call_method_value(
            "__new__",
            (
                TermValue("metaclass"),
                StringValue("Made"),
                TupleValue(()),
                TermValue("not-a-namespace"),
            ),
            owner="test",
            blame="new-site",
        )
