from __future__ import annotations

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.floor.builtin_super_value import BuiltinSuperValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

from frame_fresh import FRAME_FRESH


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
        value = node.sugar().desugar(context).completed_value()
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
    receiver = derived.fresh_receiver("receiver", allocation=FRAME_FRESH)
    zuper = BuiltinSuperValue(current_class=derived, receiver=receiver)

    projected = zuper.call_method_value(
        "__init__",
        (StringValue("v"),),
        owner="test",
        blame="super-init",
        ctx=context,
    )

    call = projected.completed_value()
    assert isinstance(call, CallSiteValue)
    # The base body runs bound to the original instance receiver, and
    # __class__ inside it is the base (so a chained super would select the
    # class after Base, not restart from Derived).
    assert call.lexical_defining_class is base
    assert call.arg_values[0] is receiver
    reduced = call.retained_source_completion_outcome()
    assert reduced.completed_value() is not None


# --- lying twin: super() naming a method no class after Derived binds ----------
_LIAR = (
    "class Base:\n"
    "    def __init__(self, x):\n"
    "        self.x = x\n"
    "\n"
    "class Derived(Base):\n"
    "    def __init__(self, x):\n"
    "        super().greet(x)\n"
)


def test_super_naming_an_absent_method_is_the_attribute_error() -> None:
    # Derived's MRO is read whole (Derived, Base, object) and no class after
    # Derived binds ``greet``: CPython's AttributeError, never a base method.
    context, (_base, derived) = _constructed(_LIAR)
    receiver = derived.fresh_receiver("receiver", allocation=FRAME_FRESH)
    zuper = BuiltinSuperValue(current_class=derived, receiver=receiver)

    outcome = zuper.call_method_value(
        "greet",
        (StringValue("v"),),
        owner="test",
        blame="super-greet",
        ctx=context,
    )

    assert outcome.halts() == outcome.exits
    assert [halt.effect.exception_name for halt in outcome.halts()] == [
        "AttributeError"
    ]


# --- a method the selected class writes, never one it inherits -----------------
_OWN_METHOD_ONLY = (
    "class Base:\n"
    "    def __init__(self, x):\n"
    "        self.x = x\n"
    "\n"
    "class Middle(Base):\n"
    "    pass\n"
    "\n"
    "class Derived(Middle):\n"
    "    def __init__(self, x):\n"
    "        super().__init__(x)\n"
)


def test_super_runs_the_first_class_after_the_cell_that_binds_the_name() -> None:
    context, (base, _middle, derived) = _constructed(_OWN_METHOD_ONLY)
    receiver = derived.fresh_receiver("receiver", allocation=FRAME_FRESH)

    call = (
        BuiltinSuperValue(current_class=derived, receiver=receiver)
        .call_method_value(
            "__init__",
            (StringValue("v"),),
            owner="test",
            blame="super-init",
            ctx=context,
        )
        .completed_value()
    )

    assert isinstance(call, CallSiteValue)
    assert call.lexical_defining_class is base


_ANNOTATED = (
    "class Base:\n"
    "    def __init__(self, match=None):\n"
    "        self.match = match\n"
    "        self._fail_reason: str | None = None\n"
    "        self._nested: bool = False\n"
    "        self.is_baseexception = False\n"
    "\n"
    "class Derived(Base):\n"
    "    def __init__(self, match=None):\n"
    "        super().__init__(match=match)\n"
    "        self.expected_exceptions = ()\n"
)


def test_super_init_statement_applies_annotated_field_stores() -> None:
    """``super().__init__(...)`` in statement position must run Base stores.

    AbstractRaises writes ``self._fail_reason: str | None = None`` in
    ``__init__``. Leaving the super CallSiteValue unreduced dropped that
    annotated store, so ``raise AssertionError(self._fail_reason)`` later
    panicked as ObjectValue.attribute. The stores have to land on the
    constructing receiver, not only fire against a nested temporal.
    """
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.floor.object_value import ObjectValue
    from sugar_lift_py_tests.floor.receiver_field_store_value import (
        ReceiverFieldStoreValue,
    )
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    context, (_base, derived) = _constructed(_ANNOTATED)
    receiver = derived.fresh_receiver("receiver", allocation=FRAME_FRESH)
    projected = receiver.call_method_value(
        "__init__",
        (),
        owner="test",
        blame="derived-init",
        ctx=context,
        keywords=(("match", NoneValue()),),
    )
    call = projected.completed_value()
    assert isinstance(call, CallSiteValue)
    reduced = call.retained_source_completion_outcome()
    assert isinstance(reduced, ExitSet), reduced
    completed = [
        face.value
        for face in reduced.exits
        if type(face).__name__ == "Completed"
    ]
    assert completed, reduced
    block = completed[-1]
    if not isinstance(block, BlockValue):
        block = BlockValue((block,), can_fall_through=True)
    # The record carries every store on the receiver: the base's, spliced
    # into the ``super().__init__`` statement's record, and the derived
    # store's post-state.
    field_names = set()
    for entry in block.statements:
        if isinstance(entry, ReceiverFieldStoreValue):
            field_names.add(entry.attr)
        elif isinstance(entry, ObjectValue):
            field_names |= {field.name for field in entry.fields}
    assert "match" in field_names
    assert "_fail_reason" in field_names
    assert "_nested" in field_names
    assert "is_baseexception" in field_names
    assert "expected_exceptions" in field_names

