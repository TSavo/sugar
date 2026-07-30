"""Enum namespace writes retain source override and builtin mutation lineage."""

from __future__ import annotations

from types import SimpleNamespace

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import (
    BuiltinDictClassValue,
    BuiltinSuperValue,
    CallSiteValue,
    MappingObjectValue,
    NoneValue,
    RuntimeClassValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


def _source_receiver(source: str):
    tree = SourceFile(
        (source, "enum_setitem_lineage.py", blake3_512_of(source.encode()))
    )
    definition = next(
        node for node in tree.root.body if isinstance(node, ClassDef)
    )
    context = ReduceContext.root(owner="test_enum_setitem_lineage")
    class_outcome = definition.sugar().desugar(context)
    assert isinstance(class_outcome, Complete)
    receiver = class_outcome.value.construct_receiver_state_from_block(
        None, "namespace-coordinate"
    )
    assert isinstance(receiver, MappingObjectValue)
    return receiver, context


def _source_method_outcome(receiver, context, key="member", value=7):
    selected = receiver.call_method_value(
        "__setitem__",
        (StringValue(key), TermValue(value)),
        owner="test_enum_setitem_lineage",
        blame="setitem-site",
        ctx=context,
    )
    assert isinstance(selected, Complete)
    assert isinstance(selected.value, CallSiteValue), (
        "a source __setitem__ override must be selected before builtin dict mutation"
    )
    return selected.value.producer_outcome(context)


def _mutation_products(outcome):
    assert isinstance(outcome, Complete)
    result = getattr(outcome.value, "result", None)
    receiver = getattr(outcome.value, "receiver", None)
    assert isinstance(result, NoneValue)
    assert isinstance(receiver, MappingObjectValue)
    return result, receiver


def test_source_setitem_halt_precedes_and_blocks_builtin_dict_mutation() -> None:
    """Lying face: direct builtin mutation cannot bypass the source override."""
    receiver, context = _source_receiver(
        "class EnumNamespace(dict):\n"
        "    def __setitem__(self, key, value):\n"
        "        raise ValueError('source override ran')\n"
    )

    outcome = _source_method_outcome(receiver, context)

    assert isinstance(outcome, ExitSet)
    halted = tuple(face for face in outcome.exits if isinstance(face, Halted))
    assert len(halted) == 1
    assert halted[0].effect.exception_name == "ValueError"
    assert receiver.entries == ()


def test_source_setitem_runs_then_super_returns_none_with_updated_receiver() -> None:
    """Truthful face: source effects precede one receiver-owned base mutation."""
    receiver, context = _source_receiver(
        "class EnumNamespace(dict):\n"
        "    def __setitem__(self, key, value):\n"
        "        self.seen = key\n"
        "        super().__setitem__(key, value)\n"
    )

    outcome = _source_method_outcome(receiver, context)
    _result, updated = _mutation_products(outcome)

    assert updated.identity == receiver.identity
    assert updated.entries == ((StringValue("member"), TermValue(7)),)
    seen = updated.attribute("seen", "seen-site")
    assert isinstance(seen, Complete)
    assert seen.value == StringValue("member")


def test_super_setitem_returns_none_and_carries_updated_namespace() -> None:
    """The builtin base call has two products; neither may replace the other."""
    base = BuiltinDictClassValue(operation="python.dict.construct")
    receiver = MappingObjectValue(
        "EnumNamespace", (), identity="namespace-coordinate", entries=()
    )
    selected_super = BuiltinSuperValue(
        current_class=SimpleNamespace(base_classes=(base,)),
        receiver=receiver,
    )

    outcome = selected_super.call_method_value(
        "__setitem__",
        (StringValue("_member_map_"), TermValue(7)),
        owner="test_enum_setitem_lineage",
        blame="super-setitem-site",
    )
    _result, updated = _mutation_products(outcome)

    assert updated.identity == receiver.identity
    assert updated.entries == ((StringValue("_member_map_"), TermValue(7)),)


def test_type_new_consumes_the_post_setitem_namespace_not_its_pre_state() -> None:
    """Deleting receiver transport makes ``_member_map_`` vanish at type.__new__."""
    type_base = SimpleNamespace(name="type")
    type_super = BuiltinSuperValue(
        current_class=SimpleNamespace(base_classes=(type_base,)),
        receiver=TermValue("metaclass"),
    )
    dict_base = BuiltinDictClassValue(operation="python.dict.construct")
    namespace = MappingObjectValue(
        "EnumNamespace", (), identity="namespace-coordinate", entries=()
    )
    dict_super = BuiltinSuperValue(
        current_class=SimpleNamespace(base_classes=(dict_base,)),
        receiver=namespace,
    )
    mutation = dict_super.call_method_value(
        "__setitem__",
        (StringValue("_member_map_"), TermValue(7)),
        owner="test_enum_setitem_lineage",
        blame="super-setitem-site",
    )
    _result, updated = _mutation_products(mutation)

    created = type_super.call_method_value(
        "__new__",
        (
            TermValue("metaclass"),
            StringValue("Made"),
            TupleValue(()),
            updated,
        ),
        owner="test_enum_setitem_lineage",
        blame="type-new-site",
    )

    assert isinstance(created, Complete)
    assert isinstance(created.value, RuntimeClassValue)
    class_dict = created.value.attribute("__dict__", "dict-site")
    assert isinstance(class_dict, Complete)
    assert class_dict.value.entries == (
        (StringValue("_member_map_"), TermValue(7)),
    )
    assert class_dict.value.entries != namespace.entries

