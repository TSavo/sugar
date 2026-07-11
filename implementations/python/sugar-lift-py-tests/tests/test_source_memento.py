"""The SourceFragment emits a SourceMemento. In-process the fragment IS the
provenance; at the membrane it projects the sealed wire form -- file, span,
source_cid (n-512 over the exact source text the fragment covers, the same
convention as the rust source oracle's blake3_512_of(body_text)). Blame is the
fragment's display projection; the memento is its wire projection; neither is
stored anywhere."""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment

_SOURCE = 'def enc(x):\n    if x == "ccc":\n        return "yyy"\n    return x\n'


def _function_def() -> SourceFragment:
    # module -> Block (the module suite) -> the FunctionDef site
    return SourceFragment.from_source(_SOURCE, "vendor.py").statements()[0].statements()[0]


def test_a_fragment_emits_its_memento() -> None:
    site = _function_def()
    memento = site.memento()
    assert memento.file == "vendor.py"
    assert memento.span.start_line == 1
    assert memento.span.end_line == 4
    assert memento.source_cid == blake3_512_of(_SOURCE.rstrip("\n").encode())


def test_a_child_fragment_covers_its_own_segment() -> None:
    site = _function_def()
    test = site.statements()[0].statements()[0].if_test()
    memento = test.memento()
    assert memento.span.start_line == 2
    assert memento.source_cid == blake3_512_of('x == "ccc"'.encode())


def test_a_sourceless_fragment_refuses_to_emit() -> None:
    # Constructed off a bare node with no source text: there is nothing to
    # content-address, and a memento without a source_cid is decorative.
    site = SourceFragment.from_node(ast.parse("pass").body[0], "t.py")
    with pytest.raises(FactoryPanic):
        site.memento()
