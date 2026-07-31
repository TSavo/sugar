"""Recon: source-defined mapping stores use the real method body and receiver state."""

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    MappingObjectValue,
    ObjectMethodValue,
    StringValue,
    TermValue,
)
from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


def _receiver(method_body: str):
    source = (
        "class _EnumDict(dict):\n"
        "    def __setitem__(self, key, value):\n"
        + "".join(f"        {line}\n" for line in method_body.splitlines())
    )
    tree = SourceFile((source, "enumdict.py", blake3_512_of(source.encode())))
    definition = next(node for node in tree.root.body if isinstance(node, ClassDef))
    ctx = ReduceContext.root(owner="enumdict-recon")
    constructed = definition.sugar().desugar(ctx)
    assert isinstance(constructed, Complete)
    receiver = constructed.value.construct_receiver_state_from_block(
        None, "enumdict-receiver"
    )
    assert isinstance(receiver, MappingObjectValue)
    return receiver, ctx


def test_enumdict_selects_an_authenticated_object_method_before_store_reduction():
    receiver, ctx = _receiver("super().__setitem__(key, value)")
    methods = tuple(method for method in receiver.methods if method.name == "__setitem__")

    assert len(methods) == 1
    assert isinstance(methods[0], ObjectMethodValue)
    assert methods[0].body is not None

    selected = receiver.call_method_value(
        "__setitem__",
        (StringValue("member"), TermValue(7)),
        owner="enumdict-recon",
        blame="enumdict.py:3:8",
        ctx=ctx,
    )
    assert isinstance(selected, Complete)
    assert isinstance(selected.value, CallSiteValue)
    assert selected.value.body is methods[0].body


def test_enumdict_single_source_setitem_returns_the_updated_receiver():
    receiver, ctx = _receiver("super().__setitem__(key, value)")

    outcome = receiver.setitem_with_context(
        StringValue("member"), TermValue(7), "enumdict.py:3:8", ctx
    )

    assert isinstance(outcome, Complete)
    updated = outcome.value
    assert isinstance(updated, MappingObjectValue)
    assert updated.identity == receiver.identity
    assert updated.entries == ((StringValue("member"), TermValue(7)),)
    assert receiver.entries == ()


def test_enumdict_field_then_mapping_store_names_the_two_mutation_join_gap():
    receiver, ctx = _receiver(
        "self.last_key = key\n"
        "super().__setitem__(key, value)"
    )

    with pytest.raises(ConstructionPanic) as raised:
        receiver.setitem_with_context(
            StringValue("member"), TermValue(7), "enumdict.py:4:8", ctx
        )

    assert raised.value.info.owner == "MappingObjectValue.setitem"
    assert raised.value.info.observed == "2 receiver-owned mutation results"
    assert raised.value.info.requested == "one authenticated __setitem__ receiver transition"
    assert receiver.entries == ()


def test_enumdict_source_halt_never_falls_through_to_builtin_storage():
    receiver, ctx = _receiver("raise ValueError('refused')")

    outcome = receiver.setitem_with_context(
        StringValue("member"), TermValue(7), "enumdict.py:3:8", ctx
    )

    assert isinstance(outcome, ExitSet)
    halted = tuple(face for face in outcome.exits if isinstance(face, Halted))
    assert len(halted) == 1
    assert halted[0].effect.exception_name == "ValueError"
    assert receiver.entries == ()
