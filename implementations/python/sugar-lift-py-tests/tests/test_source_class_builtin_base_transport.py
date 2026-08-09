from __future__ import annotations

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import (
    BlockValue,
    BuiltinDictClassValue,
    ClassValue,
    MappingObjectValue,
    ObjectValue,
)
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1


def _classes(source: str):
    tree = SourceFile(
        (source, "source_class_bases.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    return tuple(node for node in tree.root.body if isinstance(node, ClassDef))


def test_builtin_dict_base_is_evaluated_through_the_temporal_floor() -> None:
    (definition,) = _classes("class Mapping(dict):\n    pass\n")
    context = ReduceContext.root(owner="test")

    constructed = definition.sugar().desugar(context)

    assert isinstance(constructed, Complete)
    assert len(constructed.value.base_classes) == 1
    assert type(constructed.value.base_classes[0]) is BuiltinDictClassValue
    receiver = constructed.value.construct_receiver_state_from_block(None, "receiver")
    assert type(receiver) is MappingObjectValue


def test_source_subclass_transports_its_authenticated_builtin_base() -> None:
    base, derived = _classes(
        "class Mapping(dict):\n    pass\n\nclass Derived(Mapping):\n    pass\n"
    )
    context = ReduceContext.root(owner="test")
    base_value = base.sugar().desugar(context).value
    context.temporal = context.temporal.bind_value("Mapping", base_value)

    derived_value = derived.sugar().desugar(context).value

    assert derived_value.base_classes == (base_value,)
    receiver = derived_value.construct_receiver_state_from_block(None, "receiver")
    assert type(receiver) is MappingObjectValue


def test_class_named_dict_cannot_fabricate_builtin_mapping_semantics() -> None:
    (definition,) = _classes("class Mapping(dict):\n    pass\n")
    context = ReduceContext.root(owner="test")
    context.temporal = context.temporal.bind_value(
        "dict", ClassValue(name="dict", bases=(), record=BlockValue(()))
    )

    value = definition.sugar().desugar(context).value
    receiver = value.construct_receiver_state_from_block(None, "receiver")

    assert type(receiver) is ObjectValue


def test_unenrolled_non_dict_base_gains_no_new_capability() -> None:
    (definition,) = _classes("class Sequence(list):\n    pass\n")
    context = ReduceContext.root(owner="test")

    value = definition.sugar().desugar(context).value
    receiver = value.construct_receiver_state_from_block(None, "receiver")

    assert type(receiver) is ObjectValue


def test_mixed_source_and_builtin_bases_preserve_positional_roster() -> None:
    local, mixed = _classes(
        "class Local:\n    pass\n\nclass Mixed(Local, dict):\n    pass\n"
    )
    context = ReduceContext.root(owner="test")
    local_value = local.sugar().desugar(context).value
    context.temporal = context.temporal.bind_value("Local", local_value)

    mixed_value = mixed.sugar().desugar(context).value

    assert mixed_value.base_classes[0] is local_value
    assert type(mixed_value.base_classes[1]) is BuiltinDictClassValue
