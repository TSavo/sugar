"""Interning: one membrane object per site, keyed by content coordinate.

Same site -> same object, verified by ``is``. NEVER ``id()``."""

from sugar_node_membrane import Membrane
from sugar_node_membrane.nodes import Name


SRC = "x = 1\ny = x + x\n"


def test_same_source_same_membrane_same_root():
    membrane = Membrane()
    a = membrane.parse(SRC)
    b = membrane.parse(SRC)
    assert a is b


def test_walk_yields_the_same_objects_every_time():
    membrane = Membrane()
    root = membrane.parse(SRC)
    first = list(root.walk())
    second = list(root.walk())
    assert all(x is y for x, y in zip(first, second))
    assert len(first) == len(second)


def test_distinct_sites_are_distinct_objects():
    root = Membrane().parse(SRC)
    xs = [n for n in root.walk() if isinstance(n, Name) and n.id == "x"]
    # x appears at three sites: the assignment target and both operands.
    assert len(xs) == 3
    assert len({id(n) for n in xs}) == 3
    spans = {(n.span.start, n.span.end) for n in xs}
    assert len(spans) == 3


def test_pool_is_membrane_scoped_not_global():
    a = Membrane().parse(SRC)
    b = Membrane().parse(SRC)
    assert a is not b  # separate pools never share identity (ir.py precedent)


def test_filename_does_not_defeat_content_addressing():
    membrane = Membrane()
    a = membrane.parse(SRC, filename="a.py")
    b = membrane.parse(SRC, filename="b.py")
    # The coordinate is the CONTENT (source cid + span), not the filename.
    assert a is b
