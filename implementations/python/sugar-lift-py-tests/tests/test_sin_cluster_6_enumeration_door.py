"""SIN CLUSTER 6 — enumeration that bypasses the construction door.

A call binds through the frame's one binder (``bind_actuals``, not an ad-hoc
zip of flat params). ``f(a, *rest)`` called ``f(1, 2)`` packs ``rest=(2,)``; a
lying twin asserting ``rest=2`` must fail.  (The node-level binder that rebuilt
a lambda's body with the actual nodes inlined at each call,
``bind_node_actuals``, is deleted: a frame holds no body, #7757 N4.) (The seek path's own application,
``applied_contract_rows``, is deleted: a contract is applied in one place, at
prove; #7757 item 12. The universe seek by a call-site cue and its callee
resolution, ``resolve_function_for_call`` / ``find_function_by_name``, are
deleted too: no driver; #7757.)
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests import tree_enumerate as te
from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str = "cluster6.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _module_fn(source: str, name: str) -> tuple[SourceFile, FunctionDef]:
    tree = _tree(source)
    list(tree.functions())  # force bind-time rosters
    (fn,) = tuple(
        binding
        for binding in (tree.unit.module_direct_bindings or {}).get(name, ())
        if isinstance(binding, FunctionDef)
    )
    return tree, fn


# --- 1: the one binder ------------------------------------------------------


def test_seek_path_has_no_application_of_its_own() -> None:
    """#7757 item 12: enumerate does not bind and reduce a callee body itself."""
    assert not hasattr(te, "applied_contract_rows")
    assert not hasattr(te, "_args_are_ground")


def test_bind_actuals_floor_packs_rest_as_tuple_value() -> None:
    """Floor side of the same door: bind_actuals packs *rest into TupleValue."""
    from sugar_lift_py_tests.floor import TermValue, TupleValue

    source = "def f(a, *rest):\n    return rest\n"
    _tree_sf, fn = _module_fn(source, "f")
    frame = fn.source_visible_call_frame()
    bound = frame.bind_actuals((TermValue(1), TermValue(2)), ())
    assert len(bound.actuals) == 2
    rest = bound.actuals[1]
    assert rest == TupleValue((TermValue(2),))
    with pytest.raises(AssertionError):
        # Lying twin: rest is the bare second actual, not a pack.
        assert rest == TermValue(2)


def test_binding_gap_is_loud_on_arity_mismatch() -> None:
    """No silent truncate: missing required formal raises SourceCallBindingGap."""
    source = "def f(a, b):\n    return a\n"
    _tree_sf, fn = _module_fn(source, "f")
    frame = fn.source_visible_call_frame()
    with pytest.raises(SourceCallBindingGap, match="missing required formal"):
        frame.bind_actuals((), ())


def test_the_cue_seek_and_its_callee_resolution_are_gone() -> None:
    """#7757: no driver read the universe seek by a call-site cue."""
    assert not hasattr(te, "resolve_function_for_call")
    assert not hasattr(te, "find_function_by_name")
    assert not hasattr(te, "FunctionBindingMiss")
