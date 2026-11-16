"""An enum-style namespace's ``super()`` calls into builtins are the one call
(#7757 L5).

``super().__setitem__`` in a ``dict`` subclass reaches ``dict.__setitem__``,
and ``super().__new__`` in a ``type`` subclass reaches ``type.__new__``: in
each the order after ``__class__`` holds only builtins.  The lift used to
answer both by the floor (dict's mutation of the receiver, with ``None`` kept
apart; a ``RuntimeClassValue`` over the namespace), beside the dispatched
call the same lookup takes through any source class.  Now each is the one
dispatched call after ``__class__``; with no workspace root it is the one
unanswered call (``super.<name>``), owed, both faces standing.  What the
builtin does to the receiver is not stated here, so no namespace is read as
holding the stored member.
"""

from __future__ import annotations

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import (
    BuiltinSuperValue,
    CallSiteValue,
    MappingObjectValue,
    ReceiverOwnedMutationResult,
    RuntimeClassValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

from frame_fresh import FRAME_FRESH


def _source_receiver(source: str):
    tree = SourceFile(
        (source, "enum_setitem_lineage.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    definition = next(node for node in tree.root.body if isinstance(node, ClassDef))
    context = ReduceContext.root(owner="test_enum_setitem_lineage")
    class_outcome = definition.sugar().desugar(context)
    assert class_outcome.completed_value() is not None
    receiver = class_outcome.completed_value().fresh_receiver(
        "namespace-coordinate", allocation=FRAME_FRESH
    )
    assert isinstance(receiver, MappingObjectValue)
    return receiver, context


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


def _the_one_call(outcome, name: str) -> CallSiteValue:
    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == f"UnknownCallee:super.{name}"
    _binds, call = peel_walrus_binds(done.value)
    assert isinstance(call, CallSiteValue), type(call)
    assert call.body is None
    assert outcome.owed_items()
    return call


def test_super_setitem_into_dict_is_the_one_call() -> None:
    receiver, _context = _source_receiver(_SUPER_SETITEM)
    # ``type(receiver).__mro__`` is EnumNamespace, dict, object: the class
    # after the cell is ``dict``, which no namespace row states.
    outcome = BuiltinSuperValue(
        current_class=receiver.defining_class,
        receiver=receiver,
    ).call_method_value(
        "__setitem__",
        (StringValue("_member_map_"), TermValue(7)),
        owner="test_enum_setitem_lineage",
        blame="super-setitem-site",
    )

    call = _the_one_call(outcome, "__setitem__")
    assert not isinstance(call, ReceiverOwnedMutationResult)


def test_super_new_into_type_builds_no_class_here() -> None:
    metaclass = _source_class(_METACLASS)
    # ``super()`` in a metaclass's ``__new__`` binds the metaclass itself, a
    # class whose own MRO (EnumMeta, type, object) it walks.
    namespace, _context = _source_receiver(_SUPER_SETITEM)
    outcome = BuiltinSuperValue(
        current_class=metaclass, receiver=metaclass
    ).call_method_value(
        "__new__",
        (
            metaclass,
            StringValue("Made"),
            TupleValue(()),
            namespace,
        ),
        owner="test_enum_setitem_lineage",
        blame="type-new-site",
    )

    call = _the_one_call(outcome, "__new__")
    assert not isinstance(call, RuntimeClassValue)
