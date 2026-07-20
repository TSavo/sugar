"""Typeable -> Typed: the transition IS the construction event."""

import pytest

from sugar_node_membrane import Membrane, MembranePanic, Typed
from sugar_node_membrane.backend import Description, Provider, ProviderHandle
from sugar_node_membrane.nodes import SourceFragment, resolve_kind
from sugar_node_membrane.operators import operator_for
from sugar_node_membrane.spans import Span


def test_every_constructed_node_is_typed():
    root = Membrane().parse(
        "import os\n"
        "class C:\n"
        "    def m(self, *a, **k):\n"
        "        return {x: y for x, y in a if x}\n"
        "async def g():\n"
        "    async with open('f') as fh:\n"
        "        await fh.read()\n"
    )
    for node in root.walk():
        assert isinstance(node, Typed)
        assert node.resolve_type() is type(node)
        assert isinstance(node, SourceFragment)
        assert node.span.end >= node.span.start


class _BogusHandle(ProviderHandle):
    def describe(self) -> Description:
        return Description(kind="Bogus", raw_span=Span(0, 0), anchors=(), slots=())


class _BogusProvider(Provider):
    name = "bogus"

    def parse(self, unit):
        return _BogusHandle()


def test_unresolvable_typeable_panics_never_false_never_none():
    with pytest.raises(MembranePanic) as exc:
        Membrane(provider=_BogusProvider()).parse("x = 1\n")
    assert "Bogus" in exc.value.observed


def test_resolve_kind_never_returns_abstract():
    for abstract_kind in ("SourceFragment", "Statement", "Expression", "Pattern"):
        with pytest.raises(MembranePanic):
            resolve_kind(abstract_kind, observed_at="test")


def test_unknown_operator_panics():
    with pytest.raises(MembranePanic):
        operator_for("Frobnicate")
