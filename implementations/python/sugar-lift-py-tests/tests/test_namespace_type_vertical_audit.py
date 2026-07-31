"""Audit teeth for source roster -> prepared mapping -> runtime class identity."""

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import (
    BlockValue,
    BuiltinSuperValue,
    ClassValue,
    MappingObjectValue,
    NoneValue,
    ReceiverOwnedMutationResult,
    RuntimeClassValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


def _source_class(source: str):
    tree = SourceFile((source, "namespace_roster.py", blake3_512_of(source.encode())))
    node = next(item for item in tree.root.body if isinstance(item, ClassDef))
    outcome = node.sugar().desugar(ReduceContext.root(owner="namespace-audit"))
    assert isinstance(outcome, Complete)
    return outcome.value


def _type_super():
    return BuiltinSuperValue(
        current_class=type(
            "Meta",
            (),
            {"base_classes": (ClassValue(name="type", bases=(), record=None),)},
        )(),
        receiver=TermValue("metaclass"),
    )


def test_source_namespace_roster_preserves_exact_occurrence_order_and_rebinding():
    definition = _source_class(
        "class Roster:\n"
        "    zed = 1\n"
        "    def middle(self):\n"
        "        return 2\n"
        "    zed = 3\n"
        "    alpha = 4\n"
    )

    members = definition.namespace_members_in_source_order()
    coordinates = tuple(item[0] for item in members)

    assert tuple((item[1], type(item[2]).__name__) for item in members) == (
        ("zed", "TermValue"),
        ("middle", "ObjectMethodValue"),
        ("zed", "TermValue"),
        ("alpha", "TermValue"),
    )
    assert tuple((item.start_line, item.start_col) for item in coordinates) == (
        (2, 4),
        (3, 4),
        (5, 4),
        (6, 4),
    )
    assert len({item.cid for item in coordinates}) == len(coordinates)
    assert tuple(item[2].value for item in members if item[1] == "zed") == (1, 3)


def test_type_new_retains_the_exact_populated_namespace_object():
    namespace = MappingObjectValue(
        "_EnumDict",
        (),
        identity="prepared-namespace",
        entries=(
            (StringValue("first"), TermValue(1)),
            (StringValue("second"), TermValue(2)),
        ),
    )

    outcome = _type_super().call_method_value(
        "__new__",
        (
            TermValue("metaclass"),
            StringValue("Made"),
            TupleValue(()),
            namespace,
        ),
        owner="namespace-audit",
        blame="type-new-site",
    )

    assert isinstance(outcome, Complete)
    made = outcome.value
    assert isinstance(made, RuntimeClassValue)
    assert made.record is namespace
    assert made.namespace is namespace
    assert made.attribute("__dict__", "read").value is namespace


def test_runtime_class_reads_own_namespace_without_re_resolving_source_base(monkeypatch):
    base = _source_class(
        "class Base:\n"
        "    owned = 1\n"
    )
    namespace = MappingObjectValue(
        "_EnumDict",
        (),
        identity="prepared-namespace",
        entries=((StringValue("owned"), TermValue(9)),),
    )
    made = RuntimeClassValue("Made", (base,), namespace, namespace)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("consumer re-resolved a member already in its namespace")

    monkeypatch.setattr(type(base), "class_member_value", forbidden)

    assert made.attribute("owned", "read") == Complete(TermValue(9))


def test_competing_same_start_mutations_are_rejected_by_production_projector():
    start = MappingObjectValue("_EnumDict", (), identity="prepared-namespace")
    left = start.mapping_with_entries(((StringValue("left"), TermValue(1)),))
    right = start.mapping_with_entries(((StringValue("right"), TermValue(2)),))
    entries = (
        ReceiverOwnedMutationResult(start, left, NoneValue()),
        ReceiverOwnedMutationResult(start, right, NoneValue()),
    )

    with pytest.raises(ConstructionPanic) as raised:
        start._project_setitem_receiver(BlockValue(entries))

    assert raised.value.info.owner == "MappingObjectValue.setitem"
    assert "broken receiver mutation chain at position 1" in raised.value.info.observed
