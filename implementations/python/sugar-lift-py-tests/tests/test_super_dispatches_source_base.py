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
    reduced = call.retained_source_completion_outcome()
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
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    context, (_base, derived) = _constructed(_ANNOTATED)
    receiver = derived.construct_receiver_state_from_block(None, "receiver")
    projected = receiver.call_method_value(
        "__init__",
        (),
        owner="test",
        blame="derived-init",
        ctx=context,
        keywords=(("match", NoneValue()),),
    )
    assert isinstance(projected, Complete)
    call = projected.value
    assert isinstance(call, CallSiteValue)
    reduced = call.retained_source_completion_outcome()
    if isinstance(reduced, ExitSet):
        completed = [
            face.value
            for face in reduced.exits
            if type(face).__name__ == "Completed"
        ]
        assert completed, reduced
        block = completed[-1]
    else:
        assert isinstance(reduced, Complete)
        block = reduced.value
    if not isinstance(block, BlockValue):
        block = BlockValue((block,), can_fall_through=True)
    built = derived.construct_receiver_state_from_block(block, "receiver")
    assert isinstance(built, ObjectValue)
    field_names = {field.name for field in built.fields}
    assert "match" in field_names
    assert "_fail_reason" in field_names
    assert "_nested" in field_names
    assert "is_baseexception" in field_names
    assert "expected_exceptions" in field_names

