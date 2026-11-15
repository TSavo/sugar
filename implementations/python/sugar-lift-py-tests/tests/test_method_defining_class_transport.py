from __future__ import annotations

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

from frame_fresh import FRAME_FRESH


def _definitions():
    source = (
        "class Base:\n"
        "    def owner(self):\n"
        "        return __class__\n"
        "\n"
        "class Derived(Base):\n"
        "    pass\n"
    )
    tree = SourceFile(
        (source, "defining_class.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    return tuple(node for node in tree.root.body if isinstance(node, ClassDef))


def _constructed_pair():
    base, derived = _definitions()
    context = ReduceContext.root(owner="test")
    base_value = base.sugar().desugar(context).completed_value()
    context.temporal = context.temporal.bind_value("Base", base_value)
    derived_value = derived.sugar().desugar(context).completed_value()
    return context, base_value, derived_value


def test_receiver_and_inherited_method_retain_distinct_class_owners() -> None:
    _context, base, derived = _constructed_pair()

    receiver = derived.fresh_receiver("receiver", allocation=FRAME_FRESH)
    (owner_method,) = tuple(
        method for method in receiver.methods if method.name == "owner"
    )

    assert receiver.defining_class is derived
    assert owner_method.defining_class is base


