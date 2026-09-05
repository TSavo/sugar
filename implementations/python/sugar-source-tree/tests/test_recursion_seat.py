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
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )


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
