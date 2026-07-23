"""The two currencies exchange through the oracle, both directions.

fragment.seal() -> SourceMemento; resolve_memento(memento) -> an EQUAL
SourceFragment; sealing the resolved fragment reproduces an EQUAL memento.
Drift is unavailable loudly (SourceUnavailable) — never silence, never None.
"""

from pathlib import Path

import pytest
from conftest import oracle_source_file
from sugar_lift_python_source.source_oracle import SourceUnavailable, path_source
from sugar_source_tree import (
    Node,
    SourceFile,
    SourceFragment,
    SourceMemento,
    resolve_memento,
)

SOURCE = (
    "def f(a, b):\n" "    total = a + b\n" "    return total\n" "\n" "x = f(1, 2)\n"
)


def test_every_enumerated_object_answers_fragment():
    file = oracle_source_file(SOURCE)
    frag = file.fragment
    assert isinstance(frag, SourceFragment)
    assert frag.text == SOURCE
    assert frag.source_cid == file.unit.source_cid
    assert frag.node is file.root
    for node in file.nodes():
        nf = node.fragment
        assert isinstance(nf, SourceFragment)
        assert nf.node is node
        assert nf.text == node.segment()
        assert nf.source_cid == file.unit.source_cid  # same pinned text


def test_fragment_seals_and_memento_resolves_back_equal():
    file = oracle_source_file(SOURCE)
    node = next(n for n in file.nodes() if n.kind == "Return")
    frag = node.fragment

    memento = frag.seal()
    assert isinstance(memento, SourceMemento)
    assert memento.source_cid == file.unit.source_cid
    assert memento.cid.startswith("blake3-512:")

    resolved = resolve_memento(memento)
    assert resolved == frag
    assert resolved.text == frag.text == "return total"
    assert isinstance(resolved.node, Node)
    assert resolved.node.kind == "Return"

    # and back again: the resolved fragment seals to an equal memento
    assert resolved.seal() == memento


def test_file_level_fragment_round_trips():
    file = oracle_source_file(SOURCE)
    memento = file.fragment.seal()
    resolved = resolve_memento(memento)
    assert resolved == file.fragment
    assert resolved.text == SOURCE
    assert resolved.node.kind == "Module"


def test_round_trip_holds_across_backends():
    pytest.importorskip("parso")
    from sugar_source_tree.parso_adapter import ParsoBackend

    file = oracle_source_file(SOURCE)
    node = next(n for n in file.nodes() if n.kind == "Return")
    memento = node.fragment.seal()
    resolved = resolve_memento(memento, backend=ParsoBackend())
    assert resolved == node.fragment
    assert resolved.seal() == memento


def test_drifted_source_refuses_loudly_never_silence():
    file = oracle_source_file(SOURCE)
    node = next(n for n in file.nodes() if n.kind == "Return")
    memento = node.fragment.seal()
    Path(file.filename).write_text(SOURCE + "\ny = 3\n", encoding="utf-8")
    with pytest.raises(SourceUnavailable):
        resolve_memento(memento)


def test_missing_file_refuses_loudly_never_silence():
    file = oracle_source_file(SOURCE)
    memento = file.fragment.seal()
    Path(file.filename).unlink()
    with pytest.raises(SourceUnavailable):
        resolve_memento(memento)


def test_source_file_has_no_raw_text_door():
    with pytest.raises((TypeError, ValueError)):
        SourceFile(filename="<test>", source="x = 1\n")  # type: ignore[call-arg]
    assert not hasattr(SourceFile, "read")


def test_unit_carries_the_oracle_cid_verbatim():
    file = oracle_source_file(SOURCE)
    _, _, cid = path_source(file.filename)
    assert file.unit.source_cid == cid
    assert cid.startswith("blake3-512:")
