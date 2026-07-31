"""Authenticated zero-argument super transports ``type.__new__`` results."""

from dataclasses import replace

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
from sugar_lift_py_tests.floor.guarded_value import GuardedValue
from sugar_lift_py_tests.ir import atomic
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import ObjectMethodValue
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


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
    assert projected.value is namespace
    assert projected.value.entries == namespace.entries


def test_runtime_class_store_updates_the_authenticated_namespace_once() -> None:
    namespace = MappingObjectValue(
        "Namespace", (), identity="namespace-coordinate", entries=()
    )
    made = RuntimeClassValue("Made", (), namespace, namespace)

    updated = made.with_field_store("member", TermValue(7))

    assert updated.record is updated.namespace
    assert updated.namespace.identity == namespace.identity
    assert updated.attribute("member", "member-site") == Complete(TermValue(7))
    assert made.namespace.entries == ()


def test_runtime_class_rejects_equal_content_from_a_foreign_namespace_coordinate() -> None:
    namespace = MappingObjectValue(
        "Namespace", (), identity="namespace-coordinate", entries=()
    )
    made = RuntimeClassValue("Made", (), namespace, namespace)
    foreign = MappingObjectValue(
        "Namespace", (), identity="foreign-coordinate", entries=()
    )

    with pytest.raises(TypeError):
        replace(made, namespace=foreign)


def test_runtime_class_store_preserves_an_existing_receiver_partition() -> None:
    left_ns = MappingObjectValue("Namespace", (), identity="left", entries=())
    right_ns = MappingObjectValue("Namespace", (), identity="right", entries=())
    receiver = GuardedValue(
        atomic("selected-runtime-class", ()),
        RuntimeClassValue("Left", (), left_ns, left_ns),
        RuntimeClassValue("Right", (), right_ns, right_ns),
    )

    updated = receiver.with_field_store("member", TermValue(7))

    assert updated.guard == receiver.guard
    assert updated.when_true.name == "Left"
    assert updated.when_false.name == "Right"
    assert updated.when_true.attribute("member", "site") == Complete(TermValue(7))
    assert updated.when_false.attribute("member", "site") == Complete(TermValue(7))


def test_runtime_class_reads_a_member_from_its_authenticated_source_base() -> None:
    source = "class Base:\n    def inherited(self):\n        return 1\n"
    tree = SourceFile((source, "runtime_base.py", blake3_512_of(source.encode())))
    base_node = next(node for node in tree.nodes() if isinstance(node, ClassDef))
    base = base_node.sugar().desugar(ReduceContext.root(owner="test")).value
    namespace = MappingObjectValue(
        "Namespace", (), identity="namespace-coordinate", entries=()
    )
    made = RuntimeClassValue("Made", (base,), namespace, namespace)

    inherited = made.attribute("inherited", "member-site")

    assert isinstance(inherited, Complete)
    assert isinstance(inherited.value, ObjectMethodValue)
    assert inherited.value.name == "inherited"


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
