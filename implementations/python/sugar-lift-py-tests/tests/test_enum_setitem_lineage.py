"""Enum namespace writes retain source override and builtin mutation lineage."""

from __future__ import annotations

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import (
    BuiltinSuperValue,
    CallSiteValue,
    MappingObjectValue,
    NoneValue,
    RuntimeClassValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.outcome import ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1


def _source_receiver(source: str):
    tree = SourceFile(
        (source, "enum_setitem_lineage.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    definition = next(node for node in tree.root.body if isinstance(node, ClassDef))
    context = ReduceContext.root(owner="test_enum_setitem_lineage")
    class_outcome = definition.sugar().desugar(context)
    assert class_outcome.completed_value() is not None
    receiver = class_outcome.completed_value().construct_receiver_state_from_block(
        None, "namespace-coordinate"
    )
    assert isinstance(receiver, MappingObjectValue)
    return receiver, context


def _source_method_outcome(receiver, context, key="member", value=7):
    selected = receiver.bound_method_call(
        "__setitem__",
        (StringValue(key), TermValue(value)),
        owner="test_enum_setitem_lineage",
        blame="setitem-site",
        ctx=context,
    )
    assert isinstance(
        selected, CallSiteValue
    ), "a source __setitem__ override must be selected before builtin dict mutation"
    return receiver.setitem(StringValue(key), TermValue(value), "setitem-site", context)


def _mutation_products(outcome):
    assert outcome.completed_value() is not None
    result = getattr(outcome.completed_value(), "result", None)
    receiver = getattr(outcome.completed_value(), "receiver_after", None)
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
    updated = outcome.completed_value()
    assert updated is not None

    assert updated.identity == receiver.identity
    assert updated.entries == ((StringValue("member"), TermValue(7)),)
    seen = updated.attribute("seen", "seen-site", None)
    assert seen.completed_value() is not None
    assert seen.completed_value() == StringValue("member")


_SUPER_SETITEM = (
    "class EnumNamespace(dict):\n"
    "    def __setitem__(self, key, value):\n"
    "        super().__setitem__(key, value)\n"
)

_METACLASS = (
    "class EnumMeta(type):\n"
    "    def __new__(mcs, name, bases, namespace):\n"
    "        return super().__new__(mcs, name, bases, namespace)\n"
)


def _source_class(source: str):
    tree = SourceFile(
        (source, "enum_metaclass.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    definition = next(node for node in tree.root.body if isinstance(node, ClassDef))
    value = (
        definition.sugar()
        .desugar(ReduceContext.root(owner="test_enum_setitem_lineage"))
        .completed_value()
    )
    assert value is not None
    return value


def test_super_setitem_returns_none_and_carries_updated_namespace() -> None:
    """The builtin base call has two products; neither may replace the other."""
    receiver, _context = _source_receiver(_SUPER_SETITEM)
    # ``type(receiver).__mro__`` is EnumNamespace, dict, object: the class
    # after the cell that binds ``__setitem__`` is ``dict``.
    selected_super = BuiltinSuperValue(
        current_class=receiver.defining_class,
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
    metaclass = _source_class(_METACLASS)
    # ``super()`` in a metaclass's ``__new__`` binds the metaclass itself, a
    # class whose own MRO (EnumMeta, type, object) it walks: ``type.__new__``.
    type_super = BuiltinSuperValue(current_class=metaclass, receiver=metaclass)
    namespace, _context = _source_receiver(_SUPER_SETITEM)
    dict_super = BuiltinSuperValue(
        current_class=namespace.defining_class,
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

    assert created.completed_value() is not None
    assert isinstance(created.completed_value(), RuntimeClassValue)
    class_dict = created.completed_value().attribute("__dict__", "dict-site", None)
    assert class_dict.completed_value() is not None
    assert class_dict.completed_value().entries == (
        (StringValue("_member_map_"), TermValue(7)),
    )
    assert class_dict.completed_value().entries != namespace.entries
