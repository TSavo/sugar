"""Authenticated zero-argument super transports ``type.__new__`` results."""

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    BuiltinSuperValue,
    MappingObjectValue,
    RuntimeClassValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile

_METACLASS = (
    "class Meta(type):\n"
    "    def __new__(mcs, name, bases, namespace, **kwds):\n"
    "        return super().__new__(mcs, name, bases, namespace)\n"
)


def _super_value():
    # ``super()`` in a metaclass's ``__new__`` binds the metaclass itself, a
    # class whose own MRO (Meta, type, object) it walks: ``type.__new__``,
    # selected by the builtin ``type`` the base reads by binding.
    tree = SourceFile(
        (_METACLASS, "type_new_transport.py", blake3_512_of(_METACLASS.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    definition = next(node for node in tree.root.body if isinstance(node, ClassDef))
    meta = definition.sugar().desugar(ReduceContext.root(owner="test")).completed_value()
    assert meta is not None
    return BuiltinSuperValue(current_class=meta, receiver=meta)


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

    made = outcome.completed_value()
    assert made is not None
    assert isinstance(made, RuntimeClassValue)
    assert made.name == "Made"
    projected = made.attribute("__dict__", "dict-site", None)
    assert projected.completed_value() is not None
    assert projected.completed_value().entries == namespace.entries


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
