"""Binding projection paths are structural — independent of walk() policy.

Orange audit of the walk() DAG seen-set (#7110): ``_binding_site_and_path``
must not use ``enumerate(walk())`` indices. A walk index is a traversal
policy; coordinates must come from grammar structure so unique-by-id walk
cannot under-count shared Name nodes under two target edges.
"""

from __future__ import annotations

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Assign, For, Name, Tuple_
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.tree import SourceFile


def _open(text: str, name: str = "struct_path.py") -> SourceFile:
    if not text.endswith("\n"):
        text += "\n"
    return SourceFile(
        (text, name, blake3_512_of(text.encode())),
        reporter=CollectingReporter(),
    )


def test_unpack_binding_path_uses_tuple_structure_not_walk_index() -> None:
    """``a, b = 1, 2`` projects as targets/0/tuple/i — not projection/<walk i>."""
    sf = _open("def f():\n    a, b = 1, 2\n")
    fn = next(sf.functions())
    assign = next(n for n in fn.body if isinstance(n, Assign))
    site_a, path_a = assign._binding_site_and_path("a", 0)
    site_b, path_b = assign._binding_site_and_path("b", 0)
    assert path_a == ("targets", 0, "tuple", 0)
    assert path_b == ("targets", 0, "tuple", 1)
    assert "projection" not in path_a
    assert "projection" not in path_b
    assert site_a is not None and site_b is not None


def test_for_target_binding_path_is_structural() -> None:
    """``for x, y in items:`` uses target/tuple/i structure."""
    sf = _open("def f(items):\n    for x, y in items:\n        pass\n")
    fn = next(sf.functions())
    loop = next(n for n in fn.body if isinstance(n, For))
    _, path_x = loop._binding_site_and_path("x", 0)
    _, path_y = loop._binding_site_and_path("y", 0)
    assert path_x == ("target", "tuple", 0)
    assert path_y == ("target", "tuple", 1)
    assert "projection" not in path_x


def test_two_name_leaves_two_structural_coordinates() -> None:
    """Two Name leaves under one target yield two distinct structural paths.

    Even when both bind the same spelling (``x, x = …``), structure still
    distinguishes the edges. Walk-index paths would also distinguish them
    today, but only while walk is path-complete; structural paths stay correct
    if the graph later shares a Name object across edges.
    """
    sf = _open("def f():\n    x, x = 1, 2\n")
    fn = next(sf.functions())
    assign = next(n for n in fn.body if isinstance(n, Assign))
    # Collect both matches via the structural collector (Assign returns last).
    matches = []

    def collect(target, path):
        if isinstance(target, Name):
            if target.id == "x":
                matches.append(path)
            return
        if isinstance(target, Tuple_):
            for i, child in enumerate(target.elts):
                collect(child, (*path, "tuple", i))

    for ti, t in enumerate(assign.targets):
        collect(t, ("targets", ti))
    assert matches == [
        ("targets", 0, "tuple", 0),
        ("targets", 0, "tuple", 1),
    ]
    # Live binding door: last match wins (documented Assign law).
    _, path = assign._binding_site_and_path("x", 0)
    assert path == ("targets", 0, "tuple", 1)


def test_base_path_never_uses_projection_walk_token() -> None:
    """No remaining 'projection' token from the old enumerate(walk()) scheme."""
    sf = _open(
        "def f(xs):\n"
        "    a = 1\n"
        "    b, c = xs\n"
        "    for i, j in xs:\n"
        "        pass\n"
    )
    fn = next(sf.functions())
    for stmt in fn.body:
        for name in ("a", "b", "c", "i", "j"):
            _site, path = stmt._binding_site_and_path(name, 0)
            assert "projection" not in path, (type(stmt).__name__, name, path)
