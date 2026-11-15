from __future__ import annotations

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.floor.builtin_super_value import BuiltinSuperValue
from sugar_lift_py_tests.floor.named_expression_value import (
    caller_stores_of,
    peel_walrus_binds,
)
from sugar_lift_py_tests.floor.receiver_field_store_value import (
    ReceiverFieldStoreValue,
)
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


def _call_fragment(source: str, text: str):
    """The source fragment of the call spelled ``text`` in ``source``: the
    site the lifter hands a ``super().<name>(...)`` call (a ground exit
    cites the source it can re-read, never prose)."""
    from sugar_source_tree.nodes import Call

    tree = SourceFile(
        (source, "super_dispatch.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    return next(
        node.fragment
        for node in tree.nodes()
        if isinstance(node, Call) and node.fragment.text == text
    )


def _completed_call(outcome):
    """``(stores, call)``: the call ``outcome`` completes with, beneath the
    stores the body made on objects its caller sees (``CallerStoreValue``,
    ``caller_visible_stores``), which ride the call's value to the caller's
    statement; a walrus write rides none of it."""
    value = outcome.completed_value()
    assert value is not None, outcome
    binds, call = peel_walrus_binds(value)
    walrus, stores = caller_stores_of(binds)
    assert walrus == (), value
    return stores, call


def _receiver_stores(stores, receiver) -> list[tuple[str, object]]:
    """The ``(attr, value)`` of each store on ``receiver``'s identity."""
    return [
        (store.attr, store.value)
        for store in stores
        if isinstance(store, ReceiverFieldStoreValue)
        and store.receiver.identity == receiver.identity
    ]


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
        blame=_call_fragment(_LIAR, "super().greet(x)"),
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

    stores, call = _completed_call(
        BuiltinSuperValue(current_class=derived, receiver=receiver).call_method_value(
            "__init__",
            (StringValue("v"),),
            owner="test",
            blame="super-init",
            ctx=context,
        )
    )

    assert isinstance(call, CallSiteValue)
    assert call.lexical_defining_class is base
    assert _receiver_stores(stores, receiver) == [("x", StringValue("v"))]


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


