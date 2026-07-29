"""RED producer contract for source-defined ``__new__`` instance construction.

These tests intentionally stay red until the existing ClassDefinitionValue
construction door can authenticate ``__new__`` and produce an ObjectValue.
They do not add a compatibility constructor or production behavior.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_py_tests.callable_application import CallableApplication
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import ClassDefinitionValue, ObjectValue, StringValue
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _named_constant_class(*, filename: str = "named_constant.py") -> ClassDefinitionValue:
    source = (
        "class NamedIntConstant:\n"
        "    def __new__(cls, i, name):\n"
        "        item = object.__new__(cls)\n"
        "        item.name = name\n"
        "        return item\n"
        "    marker = 'unrelated'\n"
    )
    tree = SourceFile(
        (source, filename, blake3_512_of(source.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    definition = next(
        node for node in tree.root.body if node.kind == "ClassDef"
    )
    outcome = definition.sugar().desugar()
    assert type(outcome.value) is ClassDefinitionValue
    return outcome.value


def _apply(value, arguments):
    return CallableApplication(
        tuple(arguments), (), "named-int-constant.__new__"
    ).apply(value, None)


def test_truthful_new_constructs_object_and_preserves_unrelated_field():
    value = _named_constant_class()
    outcome = _apply(value, (StringValue("7"), StringValue("X")))
    assert type(outcome.value) is ObjectValue
    assert outcome.value.attribute("name", "site").value == StringValue("X")
    assert value.class_fields[0].name == "marker"


@pytest.mark.parametrize(
    "lying",
    [
        "foreign same-signature __new__",
        "foreign call occurrence",
        "swapped formal coordinates",
        "wrong cls testimony",
        "non-ObjectValue return",
        "missing __new__ owner",
    ],
)
def test_lying_new_testimony_refuses_before_object_mutation(lying: str):
    value = _named_constant_class(filename=f"{lying.replace(' ', '_')}.py")
    if lying == "foreign same-signature __new__":
        value = replace(value, class_definition_cid="foreign-class-cid")
    with pytest.raises(SugarNotWritten, match=lying):
        _apply(value, (StringValue("7"), StringValue("X")))
