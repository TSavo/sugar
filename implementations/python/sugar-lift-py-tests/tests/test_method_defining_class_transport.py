from __future__ import annotations

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


def _definitions():
    source = (
        "class Base:\n"
        "    def owner(self):\n"
        "        return __class__\n"
        "\n"
        "class Derived(Base):\n"
        "    pass\n"
    )
    tree = SourceFile((source, "defining_class.py", blake3_512_of(source.encode())))
    return tuple(node for node in tree.root.body if isinstance(node, ClassDef))


def _constructed_pair():
    base, derived = _definitions()
    context = ReduceContext.root(owner="test")
    base_value = base.sugar().desugar(context).value
    context.temporal = context.temporal.bind_value("Base", base_value)
    derived_value = derived.sugar().desugar(context).value
    return context, base_value, derived_value


def test_receiver_and_inherited_method_retain_distinct_class_owners() -> None:
    _context, base, derived = _constructed_pair()

    receiver = derived.construct_receiver_state_from_block(None, "receiver")
    (owner_method,) = tuple(method for method in receiver.methods if method.name == "owner")

    assert receiver.defining_class is derived
    assert owner_method.defining_class is base


def test_inherited_method_binds_lexical_class_not_runtime_receiver_class() -> None:
    context, base, derived = _constructed_pair()
    receiver = derived.construct_receiver_state_from_block(None, "receiver")

    projected = receiver.call_method_value(
        "owner", (), owner="test", blame="call-owner", ctx=context
    )

    assert isinstance(projected, Complete)
    assert isinstance(projected.value, CallSiteValue)
    assert projected.value.lexical_defining_class is base
    reduced = projected.value.reduce_source_outcome(context)
    assert isinstance(reduced, Complete)
    assert reduced.value.statements[0].value is base


def test_overriding_method_uses_derived_defining_class() -> None:
    base, _ = _definitions()
    source = (
        "class Derived:\n"
        "    def owner(self):\n"
        "        return __class__\n"
    )
    tree = SourceFile((source, "derived_owner.py", blake3_512_of(source.encode())))
    (derived,) = tuple(node for node in tree.root.body if isinstance(node, ClassDef))
    context = ReduceContext.root(owner="test")
    derived_value = derived.sugar().desugar(context).value
    receiver = derived_value.construct_receiver_state_from_block(None, "receiver")

    projected = receiver.call_method_value(
        "owner", (), owner="test", blame="call-owner", ctx=context
    ).value

    assert projected.lexical_defining_class is derived_value
    reduced = projected.reduce_source_outcome(context)
    assert reduced.value.statements[0].value is derived_value
