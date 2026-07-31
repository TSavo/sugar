from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import (
    BlockValue,
    BuiltinObjectClassValue,
    BuiltinSemanticCallable,
    ClassValue,
    StringValue,
)
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.temporal import builtin_name_bindings
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Attribute
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.gap.panic import ConstructionPanic


def _sites():
    source = "object.__str__\nobject.missing\n"
    tree = SourceFile((source, "builtin_object.py", blake3_512_of(source.encode())))
    return tuple(node.fragment for node in tree.nodes() if isinstance(node, Attribute))


def test_builtin_object_is_static_and_owns_only_its_closed_callable_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(builtin_name_bindings, "_EMPTY_BUILTIN_TEMPORAL", None)
    monkeypatch.setattr(
        builtin_name_bindings, "builtin_callable_names", lambda: frozenset()
    )
    temporal = builtin_name_bindings.builtin_name_temporal()
    receiver = temporal.value_for("object")
    member_site, missing_site = _sites()

    assert type(receiver) is BuiltinObjectClassValue
    outcome = receiver.attribute("__str__", member_site)
    assert isinstance(outcome, Complete)
    assert type(outcome.value) is BuiltinSemanticCallable
    assert outcome.value.operation == "python.object.__str__"
    assert outcome.value.to_term(owner="test") == BuiltinSemanticCallable(
        operation="python.object.__str__"
    ).to_term(owner="test")
    with pytest.raises(ConstructionPanic):
        receiver.attribute("missing", missing_site)

    ordinary = ClassValue(name="object", bases=(), record=BlockValue(()))
    with pytest.raises(ConstructionPanic):
        ordinary.attribute("__str__", member_site)
    name = receiver.attribute("__name__", member_site)
    qualname = receiver.attribute("__qualname__", member_site)
    assert name == Complete(StringValue("object"))
    assert qualname == Complete(StringValue("object"))


@pytest.mark.parametrize(
    "member",
    ("__format__", "__new__", "__reduce_ex__", "__repr__", "__str__"),
)
def test_builtin_object_closed_data_model_members_are_authenticated(member) -> None:
    receiver = BuiltinObjectClassValue(name="object", bases=(), record=None)

    projected = receiver.attribute(member, _sites()[0])

    assert projected == Complete(
        BuiltinSemanticCallable(operation=f"python.object.{member}")
    )
