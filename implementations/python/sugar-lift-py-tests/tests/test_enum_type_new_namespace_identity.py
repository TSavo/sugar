"""``EnumType.__new__`` preserves its authenticated namespace coordinate.

The source call is::

    super().__new__(metacls, cls, bases, classdict, **kwds)

``type.__new__`` may mint a runtime class only from the supplied mapping.  Its
``__dict__`` projection is that mapping testimony, not a copied dictionary and
never a mapping selected later by spelling or equal entries.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.floor import (
    BuiltinSuperValue,
    ClassValue,
    MappingObjectValue,
    RuntimeClassValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.panic import BackendDefect


def _namespace(identity: str, value: int = 7) -> MappingObjectValue:
    return MappingObjectValue(
        "_EnumDict",
        (),
        identity=identity,
        entries=((StringValue("member"), TermValue(value)),),
    )


def _type_super(base=None) -> BuiltinSuperValue:
    if base is None:
        base = ClassValue(name="type", bases=(), record=None)
    return BuiltinSuperValue(
        current_class=SimpleNamespace(base_classes=(base,)),
        receiver=TermValue("metacls"),
    )


def _make_runtime_class(namespace: MappingObjectValue):
    return _type_super().call_method_value(
        "__new__",
        (
            TermValue("metacls"),
            StringValue("MadeEnum"),
            TupleValue(()),
            namespace,
        ),
        owner="EnumType.__new__",
        blame="Lib/enum.py:560:19",
        keywords=(("**", _namespace("kwds-coordinate", value=9)),),
    )


def test_enum_type_new_dict_is_the_exact_supplied_mapping_namespace() -> None:
    """Truthful arm: the constructor transports one namespace object end to end."""
    namespace = _namespace("classdict-coordinate")

    created = _make_runtime_class(namespace)

    assert isinstance(created, Complete)
    assert isinstance(created.value, RuntimeClassValue)
    assert created.value.record is namespace
    assert created.value.namespace is namespace
    class_dict = created.value.attribute("__dict__", "Lib/enum.py:566:16")
    assert isinstance(class_dict, Complete)
    assert class_dict.value is namespace


def test_runtime_class_refuses_foreign_namespace_coordinate() -> None:
    """Lying arm: equal mapping contents cannot replace the constructor operand."""
    supplied = _namespace("classdict-coordinate")
    foreign = _namespace("foreign-classdict-coordinate")
    created = _make_runtime_class(supplied)
    assert isinstance(created, Complete)
    assert isinstance(created.value, RuntimeClassValue)

    corrupted = replace(created.value, namespace=foreign)
    with pytest.raises(BackendDefect, match="namespace|record|coordinate"):
        corrupted.attribute("__dict__", "Lib/enum.py:566:16")


def test_symbolic_selected_base_cannot_mint_type_new_result() -> None:
    """Lying arm: an unresolved object named like ``type`` grants no authority."""
    unresolved_type = SymbolicValue(make_var("type"))

    with pytest.raises(
        ConstructionPanic,
        match="observed=SymbolicValue.__new__|selected-base method semantics",
    ):
        _type_super(unresolved_type).call_method_value(
            "__new__",
            (
                TermValue("metacls"),
                StringValue("MadeEnum"),
                TupleValue(()),
                _namespace("classdict-coordinate"),
            ),
            owner="EnumType.__new__",
            blame="Lib/enum.py:560:19",
        )
