from __future__ import annotations

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.floor.builtin_super_value import BuiltinSuperValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1


def _constructed(source: str):
    tree = SourceFile(
        (source, "super_dispatch.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    context = ReduceContext.root(owner="test")
    values = []
    for node in tree.root.body:
        if not isinstance(node, ClassDef):
            continue
        value = node.sugar().desugar(context).value
        context.temporal = context.temporal.bind_value(value.class_name, value)
        values.append(value)
    return context, values


# --- truthful twin: zero-arg super() into a same-module source base -----------
_TRUTHFUL = (
    "class Base:\n"
    "    def __init__(self, x):\n"
    "        self.x = x\n"
    "\n"
    "class Derived(Base):\n"
    "    def __init__(self, x):\n"
    "        super().__init__(x)\n"
)


def test_super_dispatches_into_source_defined_base_init() -> None:
    context, (base, derived) = _constructed(_TRUTHFUL)
    receiver = derived.construct_receiver_state_from_block(None, "receiver")
    zuper = BuiltinSuperValue(current_class=derived, receiver=receiver)

    projected = zuper.call_method_value(
        "__init__",
        (StringValue("v"),),
        owner="test",
        blame="super-init",
        ctx=context,
    )

    assert isinstance(projected, Complete)
    call = projected.value
    assert isinstance(call, CallSiteValue)
    # The base body runs bound to the original instance receiver, and
    # __class__ inside it is the base (so a chained super would select the
    # class after Base, not restart from Derived).
    assert call.lexical_defining_class is base
    assert call.arg_values[0] is receiver
    reduced = call.reduce_source_outcome(context)
    assert isinstance(reduced, Complete)


# --- lying twin: super() naming a method no base defines must stay loud --------
_LIAR = (
    "class Base:\n"
    "    def __init__(self, x):\n"
    "        self.x = x\n"
    "\n"
    "class Derived(Base):\n"
    "    def __init__(self, x):\n"
    "        super().greet(x)\n"
)


def test_super_refuses_absent_base_method() -> None:
    context, (base, derived) = _constructed(_LIAR)
    receiver = derived.construct_receiver_state_from_block(None, "receiver")
    zuper = BuiltinSuperValue(current_class=derived, receiver=receiver)

    with pytest.raises(SugarNotWritten):
        zuper.call_method_value(
            "greet",
            (StringValue("v"),),
            owner="test",
            blame="super-greet",
            ctx=context,
        )
