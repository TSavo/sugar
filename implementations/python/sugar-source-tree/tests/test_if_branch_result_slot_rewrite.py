"""RED: an If rewrite retains its one authenticated branch-result slot."""

from __future__ import annotations

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.binding_state import branch_result_slot
from sugar_source_tree.nodes import If
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.tree import SourceFile


def _ifs() -> tuple[If, If]:
    source = (
        "if first:\n"
        "    pass\n"
        "else:\n"
        "    pass\n"
        "if second:\n"
        "    pass\n"
        "else:\n"
        "    pass\n"
    )
    source_file = SourceFile((source, "if_slot.py", blake3_512_of(source.encode())))
    found = tuple(node for node in source_file.nodes() if isinstance(node, If))
    assert len(found) == 2
    return found


def test_substitute_on_slotted_if_reuses_without_contacting_mint_door(
    monkeypatch,
) -> None:
    exact, _foreign = _ifs()
    slot = branch_result_slot(exact.test)
    first = exact._rewrite_with_slot({}, slot, authenticated_slot=slot)
    mint_contacts = 0
    original = If._rewrite_with_slot

    def observed_mint(self, *args, **kwargs):
        nonlocal mint_contacts
        mint_contacts += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(If, "_rewrite_with_slot", observed_mint)
    second = first.substitute({})

    assert mint_contacts == 0
    assert first.branch_result_slot_id == slot.slot_id
    assert first.authenticated_branch_result_slot_id == slot.slot_id
    assert second.branch_result_slot_id == slot.slot_id
    assert second.authenticated_branch_result_slot_id == slot.slot_id


def test_duplicate_or_foreign_branch_slot_never_replaces_the_exact_slot() -> None:
    exact, foreign = _ifs()
    exact_slot = branch_result_slot(exact.test)
    foreign_slot = branch_result_slot(foreign.test)
    first = exact._rewrite_with_slot({}, exact_slot, authenticated_slot=exact_slot)

    assert foreign_slot.slot_id != exact_slot.slot_id
    for attempted in (exact_slot, foreign_slot):
        with pytest.raises(
            BackendDefect,
            match="the one slot authenticated for this exact If.test",
        ):
            first._rewrite_with_slot({}, attempted, authenticated_slot=attempted)

    assert first.branch_result_slot_id == exact_slot.slot_id
    assert first.authenticated_branch_result_slot_id == exact_slot.slot_id
