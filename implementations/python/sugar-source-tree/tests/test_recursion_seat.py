"""Recursion is a seat, not an unfolding (6 RecursionError files, 2026-09-05 board).

A same-module callee's universe / frame is constructed inline at its call.
Along ``ensure_key_mapped <-> _ensure_key_mapped_multiindex`` (pandas
core/sorting.py) that re-entered the definition under construction until
RecursionError. The fixpoint reference is the definition itself: re-entry
raises ``SourceCallFrameCycle`` at the door and the asking call becomes a
seat -- definition known, ``call-graph-cycle`` resolution gap, no second body.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_source_tree.nodes import (
    _FRAMES_UNDER_CONSTRUCTION,
    Call,
    FunctionDef,
    SourceCallFrameCycle,
)
from sugar_source_tree.reporter import CollectingReporter

MUTUAL = (
    "def ensure_mapped(values, key):\n"
    "    if isinstance(values, tuple):\n"
    "        return ensure_mapped_multi(values, key)\n"
    "    return key(values)\n"
    "\n"
    "def ensure_mapped_multi(values, key):\n"
    "    return tuple(ensure_mapped(v, key) for v in values)\n"
    "\n"
    "def entry(values, key):\n"
    "    return ensure_mapped(values, key)\n"
)


def _open(tmp_path, source: str):
    path = tmp_path / "mutual.py"
    path.write_text(source)
    return open_source_file_for_construction(
        path,
        root=tmp_path,
        reporter=CollectingReporter(),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),    )


def _calls(sugar):
    """Every CallSiteSugar reachable through dataclass fields, tuples, lists."""
    import dataclasses

    seen, out, stack = set(), [], [sugar]
    while stack:
        o = stack.pop()
        if id(o) in seen:
            continue
        seen.add(id(o))
        if isinstance(o, CallSiteSugar):
            out.append(o)
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            for f in dataclasses.fields(o):
                if f.name != "site":
                    stack.append(getattr(o, f.name))
        elif isinstance(o, (tuple, list)):
            stack.extend(o)
    return out


def test_mutual_recursion_constructs_with_a_seat(tmp_path) -> None:
    """Truthful twin: the entry universe constructs; the cycle is one seat."""
    source_file = _open(tmp_path, MUTUAL)
    entry = next(f for f in source_file.functions() if f.name == "entry")
    sugar = entry.sugar()
    seats = [
        c for c in _calls(sugar)
        if (c.contract_resolution_gap or "").startswith("call-graph-cycle:")
    ]
    assert seats, "the recursive call must carry the call-graph-cycle seat"
    for seat in seats:
        # No inlined FRAME for an active definition -- that is the lie the
        # seat forbids. A universe reference may be present: it is the
        # definition's own (cached) meaning, i.e. the fixpoint reference.
        assert seat.source_call_frame is None
        assert isinstance(seat.expected_definition_ref, FunctionDef)
        assert seat.expected_definition_ref.name in {"ensure_mapped", "ensure_mapped_multi"}
        if seat.formal_function_sugar is not None:
            assert seat.formal_function_sugar.name == seat.expected_definition_ref.name
    assert not _FRAMES_UNDER_CONSTRUCTION, "the active set is empty after construction"


def test_non_recursive_call_still_inlines_its_frame(tmp_path) -> None:
    """The seat law never touches a call that does not recurse."""
    source_file = _open(
        tmp_path,
        "def helper(v):\n    return v\n\ndef entry(v):\n    return helper(v)\n",
    )
    entry = next(f for f in source_file.functions() if f.name == "entry")
    calls = _calls(entry.sugar())
    assert calls and all(c.contract_resolution_gap is None for c in calls)
    assert all(c.formal_function_sugar is not None for c in calls)


def test_reentry_at_the_door_is_refused_not_unfolded(tmp_path) -> None:
    """Lying twin: asking for a universe already under construction is a cycle."""
    source_file = _open(tmp_path, MUTUAL)
    definition = next(f for f in source_file.functions() if f.name == "ensure_mapped")
    cid = definition.fragment.seal().cid
    _FRAMES_UNDER_CONSTRUCTION.add(cid)
    try:
        with pytest.raises(SourceCallFrameCycle):
            definition.source_visible_call_frame()
    finally:
        _FRAMES_UNDER_CONSTRUCTION.discard(cid)


SHARED = (
    "def leaf(v):\n"
    "    return v\n"
    "\n"
    "def mid(v):\n"
    "    return leaf(v) + leaf(v)\n"
    "\n"
    "def entry(v):\n"
    "    return mid(v) + mid(v) + leaf(v)\n"
)


def _count_frame_constructions(monkeypatch) -> dict[str, int]:
    """Count real frame constructions per definition name (memo hits excluded)."""
    built: dict[str, int] = {}
    construct = FunctionDef._source_visible_call_frame_unguarded

    def counted(self):
        built[self.name] = built.get(self.name, 0) + 1
        return construct(self)

    monkeypatch.setattr(FunctionDef, "_source_visible_call_frame_unguarded", counted)
    return built


def test_shared_callee_frame_is_constructed_once(tmp_path, monkeypatch) -> None:
    """Truthful twin: one definition, one frame, however many sites call it.

    pandas/_testing/asserters.py rebuilt every callee frame at every call
    site, and theirs below it, so the work multiplied down each call chain
    and the file ran past the 80 s ceiling. The frame is the definition's
    own meaning: five sites of ``leaf`` and two of ``mid`` read one frame
    each.
    """
    built = _count_frame_constructions(monkeypatch)
    source_file = _open(tmp_path, SHARED)
    entry = next(f for f in source_file.functions() if f.name == "entry")
    calls = _calls(entry.sugar())
    assert len(calls) >= 3
    assert all(c.contract_resolution_gap is None for c in calls)
    assert all(c.formal_function_sugar is not None for c in calls)
    assert built == {"leaf": 1, "mid": 1}
    assert not _FRAMES_UNDER_CONSTRUCTION


def test_frame_built_under_an_open_definition_is_not_served_elsewhere(
    tmp_path, monkeypatch
) -> None:
    """Lying twin: a frame holding a recursion seat answers only that recursion.

    ``ensure_mapped_multi`` built while ``ensure_mapped`` is open carries a
    ``call-graph-cycle`` seat in place of ``ensure_mapped``'s frame. Serving
    that frame to an asker with nothing open would report a recursion that
    is not there, so the second asker constructs its own; the first asker,
    asking again under the same open definition, reads the one it built.
    """
    built = _count_frame_constructions(monkeypatch)
    source_file = _open(tmp_path, MUTUAL)
    functions = {f.name: f for f in source_file.functions()}
    outer = functions["ensure_mapped"]
    inner = functions["ensure_mapped_multi"]
    outer_cid = outer.fragment.seal().cid

    _FRAMES_UNDER_CONSTRUCTION.add(outer_cid)
    try:
        inner.source_visible_call_frame()
        assert built == {"ensure_mapped_multi": 1}
        inner.source_visible_call_frame()
        assert built == {"ensure_mapped_multi": 1}, "same open set reads the memo"
    finally:
        _FRAMES_UNDER_CONSTRUCTION.discard(outer_cid)

    inner.source_visible_call_frame()
    assert built["ensure_mapped_multi"] == 2, (
        "a frame built under an open definition was served with nothing open"
    )
    assert built["ensure_mapped"] == 1
    assert not _FRAMES_UNDER_CONSTRUCTION
