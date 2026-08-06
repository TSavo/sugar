"""L0a: authenticated constructor shape door — construct or panic, never AttributeError.

_authenticated_new_constructor_shape is ClassDef's __new__ allocation pattern.
Non-class nodes must answer None (base method), not AttributeError.
retain_registered_node_from must enroll CollectingReporter file-open
occurrences into a ConstructionTestimony consumer roll (same door that
blocked module materialize on real pandas).
"""

from __future__ import annotations

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.backend import materialize
from sugar_source_tree.binding_state import (
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
)
from sugar_source_tree.nodes import Call, ClassDef, FunctionDef, Name, Node
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.tree import SourceFile


def _sf(source: str, name: str = "l0a.py") -> SourceFile:
    return SourceFile((source, name, blake3_512_of(source.encode("utf-8"))))


def test_non_class_nodes_answer_none_for_constructor_shape() -> None:
    """Base door: FunctionDef / Call never AttributeError on the shape probe."""
    source = _sf(
        "def f(n):\n"
        "    if n:\n"
        "        return f(n - 1)\n"
        "    return 0\n"
        "\n"
        "f(2)\n"
    )
    for node in source.nodes():
        if isinstance(node, ClassDef):
            continue
        # Must not raise AttributeError
        shape = node._authenticated_new_constructor_shape()
        assert shape is None, f"{type(node).__name__} must answer None, got {shape!r}"


def test_classdef_with_authenticated_new_shape_constructs() -> None:
    """Truthful twin: recognized __new__ allocation shape is non-None and sugars."""
    source = _sf(
        "class Box:\n"
        "    def __new__(cls, value):\n"
        "        self = super(Box, cls).__new__(cls)\n"
        "        self.value = value\n"
        "        return self\n"
        "\n"
        "Box(1)\n"
    )
    cls = next(n for n in source.nodes() if isinstance(n, ClassDef) and n.name == "Box")
    shape = cls._authenticated_new_constructor_shape()
    assert shape is not None
    sugar = cls.sugar()
    assert sugar is not None
    call = next(
        n
        for n in source.nodes()
        if isinstance(n, Call) and isinstance(n.func, Name) and n.func.id == "Box"
    )
    assert call.sugar() is not None


def test_collecting_reporter_producer_retains_into_testimony_consumer() -> None:
    """File-open CollectingReporter is a lawful producer for retain (not BackendDefect)."""
    source = "def exact():\n    return 1\n"
    identity = (source, "retain_collect.py", blake3_512_of(source.encode()))
    collector = CollectingReporter()
    tree = SourceFile(identity, reporter=collector)
    # Ordinary open: definition lives on CollectingReporter, not testimony table.
    definition = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    assert definition.reporter is collector

    consumer = ConstructionTestimonyReporterV1(
        CollectingReporter(),
        SubstitutionTraceBuilderV1(tree.unit.source_cid),
    )
    retained = consumer.retain_registered_node_from(definition, collector)
    assert retained is definition
    assert consumer.materialized_node_for_ref(definition.ref) is definition


def test_null_reporter_producer_still_panics() -> None:
    """Lying twin: NullReporter never owned the registration — stay loud."""
    from sugar_source_tree.reporter import NullReporter

    source = "def exact():\n    return 1\n"
    identity = (source, "retain_null.py", blake3_512_of(source.encode()))
    collector = CollectingReporter()
    tree = SourceFile(identity, reporter=collector)
    definition = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    consumer = ConstructionTestimonyReporterV1(
        CollectingReporter(),
        SubstitutionTraceBuilderV1(tree.unit.source_cid),
    )
    try:
        consumer.retain_registered_node_from(definition, NullReporter())
        raise AssertionError("expected BackendDefect for NullReporter producer")
    except BackendDefect as gap:
        # The refusal now names WHICH fault. A NullReporter producer owns no
        # registration table at all; that is absence (a seating defect at the
        # door that opened the tree), not a foreign occurrence. See
        # test_retention_refusal_names_which_fault.py.
        assert "producer reporter owns no registration table" in gap.observed
        assert "NullReporter" in gap.observed
