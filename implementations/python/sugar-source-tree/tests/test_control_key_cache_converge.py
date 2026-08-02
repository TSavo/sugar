"""Control stacks belong in the construction key only for control-sensitive kinds.

A Name under two loop depths shares one field row. A Break under two nearest
loops keeps two rows. Nested-loop construction still resolves each break to
its own target.
"""

from __future__ import annotations

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.construction_cache import ConstructionCache
from sugar_source_tree.nodes import ControlConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    return next(SourceFile(path_source(path)).functions())


def test_nested_breaks_sugar_targets_nearest_loop_with_shared_field_cache():
    function = _function(
        "def f(xs, ys):\n"
        "    for x in xs:\n"
        "        for y in ys:\n"
        "            if y:\n"
        "                break\n"
        "        if x:\n"
        "            break\n"
    )
    breaks = [n for n in function.walk() if n.kind == "Break"]
    assert len(breaks) == 2
    targets = [br.sugar().target_cid for br in breaks]
    assert targets[0] != targets[1], (
        "inner and outer break must not share a loop target "
        f"(got {targets!r})"
    )
    cache = function.unit.construction_cache
    assert cache is not None
    control_bearing = sum(1 for key in cache.fields if key[3])
    plain = sum(1 for key in cache.fields if not key[3])
    # Non-sensitive kinds dominate; control fragments are rare (breaks).
    assert plain > control_bearing
    assert control_bearing >= 1


def test_name_field_key_ignores_loop_stack():
    cache = ConstructionCache()
    ref, reporter = object(), object()
    outer = object()
    a = ControlConstructionContextV1().enter_loop(outer)
    b = a.enter_loop(object())
    assert cache.key(ref, reporter, a, kind="Name") == cache.key(
        ref, reporter, b, kind="Name"
    )
    assert cache.key(ref, reporter, a, kind="Break") != cache.key(
        ref, reporter, b, kind="Break"
    )
