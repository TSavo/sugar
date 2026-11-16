"""Undecided attribution sweep — do not count source-undecided as missing Floor.

ImportMemberValue already wires subscript/attribute/contains into
FloorValue.undecided_* (#import-member ops). This file pins the *same* law for
other value types that still fell through to:

  write more Floor: implement {Type}.attribute

when the honest answer is "runtime type not lift-time decided".

Triage: vocabulary already exists on FloorValue; offenders were wrong entrance
(base construction-panic arm), not empty building.
"""

from __future__ import annotations

from types import SimpleNamespace

from sugar_lift_py_tests.floor.mutable_global_value import MutableGlobalValue
from sugar_source_tree.fragment import SourceMemento

_CID = "blake3-512:" + ("ab" * 64)
_CID2 = "blake3-512:" + ("cd" * 64)


def _pinned(tmp_path, monkeypatch, source: str, kind: str, node_type):
    """A pin of the module binding ``G`` and the real source fragment of the
    first ``node_type`` node that reads it: what the lifter hands the floor
    (a site that names its source coordinate), never a stand-in."""
    from sugar_lift_py_tests.lift_rpc import _open_at_seat
    from sugar_source_tree.nodes import Name

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "undecided_sweep.py"
    path.write_text(source)
    tree = _open_at_seat(path, root=tmp_path)
    binding = next(
        node.fragment
        for node in tree.nodes()
        if isinstance(node, Name) and node.fragment.text == "G"
    )
    site = next(node for node in tree.nodes() if isinstance(node, node_type)).fragment
    pin = MutableGlobalValue("G", kind, binding.source_cid, binding.seal())
    return pin, site


def _mutable(*, kind: str = "list") -> MutableGlobalValue:
    memento = SourceMemento(
        file="mod.py",
        source_cid=_CID,
        cid=_CID2,
        start=0,
        end=1,
    )
    return MutableGlobalValue(
        name="g",
        kind=kind,
        pin_source_cid=_CID,
        binding_memento=memento,
    )


def _assert_undecided_membership_faces(outcome) -> None:
    """Undecided membership is the two faces, not a refusal or a write-more-Floor."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet)
    (completed,) = [f for f in outcome.exits if isinstance(f, Completed)]
    (halted,) = [f for f in outcome.exits if isinstance(f, Halted)]
    assert completed.guard.name == "python:compare.completes"
    # The undecided membership, keyed per evaluation (#7757 NEW-1).
    assert completed.value.formula.name == "python:compare_result"
    assert completed.value.formula.args[0].value == "In"
    assert isinstance(halted.effect, UndeterminedRaiseEffect)
    assert halted.effect.producer_node_owner == "UndecidedCompare:In"


def test_mutable_global_non_dict_contains_is_undecided_not_write_more_floor(
    tmp_path, monkeypatch
) -> None:
    """kind!=dict used super().contains → write more Floor: implement MutableGlobalValue.contains."""
    from sugar_source_tree.nodes import Compare

    v, site = _pinned(
        tmp_path, monkeypatch, "G = []\nfound = 0 in G\n", "list", Compare
    )
    assert v.runtime_type_is_decided() is False
    from sugar_lift_py_tests.floor.term_value import TermValue

    _assert_undecided_membership_faces(v.contains(TermValue(0), site))


def test_mutable_global_attribute_is_undecided_not_write_more_floor(
    tmp_path, monkeypatch
) -> None:
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_source_tree.nodes import Attribute

    v, site = _pinned(
        tmp_path, monkeypatch, "G = {}\nkeys = G.keys\n", "dict", Attribute
    )
    outcome = v.attribute("keys", site, None)
    (halt,) = [arm for arm in outcome.exits if isinstance(arm, Halted)]
    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.effect.producer_node_owner == "MutableGlobalValue.attribute"
    assert done.guard.name == "python:attribute_op.completes"


def test_mutable_global_dict_contains_still_constructs() -> None:
    """Do not break decided dict membership on the pin."""
    from sugar_lift_py_tests.floor.term_value import TermValue

    v = _mutable(kind="dict")
    site_ok = SimpleNamespace(
        __str__=lambda self: "site:mod.py:1:1",
        source_cid=_CID,
    )
    outcome = v.contains(TermValue(1), site_ok)
    assert outcome.completed_value() is not None
