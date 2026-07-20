"""Typeable -> Typed: the transition IS the construction event."""

import pytest

from conftest import oracle_source_file
from sugar_source_tree import SourceFile, SourceTreePanic, Typed
from sugar_source_tree.backend import Description, Backend, BackendNode
from sugar_source_tree.nodes import Node, resolve_kind
from sugar_source_tree.operators import operator_for
from sugar_source_tree.spans import Span


def test_every_constructed_node_is_typed():
    root = oracle_source_file((
        "import os\n"
        "class C:\n"
        "    def m(self, *a, **k):\n"
        "        return {x: y for x, y in a if x}\n"
        "async def g():\n"
        "    async with open('f') as fh:\n"
        "        await fh.read()\n"
    )).root
    for node in root.walk():
        assert isinstance(node, Typed)
        assert node.resolve_type() is type(node)
        assert isinstance(node, Node)
        assert node.span.end >= node.span.start


class _BogusHandle(BackendNode):
    def describe(self) -> Description:
        return Description(kind="Bogus", raw_span=Span(0, 0), anchors=(), slots=())


class _BogusBackend(Backend):
    name = "bogus"

    def root(self, unit):
        return _BogusHandle()


def test_unresolvable_typeable_panics_never_false_never_none():
    with pytest.raises(SourceTreePanic) as exc:
        oracle_source_file("x = 1\n", backend=_BogusBackend())
    assert "Bogus" in exc.value.observed


def test_resolve_kind_never_returns_abstract():
    for abstract_kind in ("Node", "Statement", "Expression", "Pattern"):
        with pytest.raises(SourceTreePanic):
            resolve_kind(abstract_kind, observed_at="test")


def test_unknown_operator_panics():
    with pytest.raises(SourceTreePanic):
        operator_for("Frobnicate")
