"""An owner's reduction is a memo row like any other (#7838, #7757 item 44).

``tree_enumerate.owner_reduction`` remembers each reduction through the one
memo door: a reduction that read an ambient value is reduced again where that
value differs and served where it matches; one that read none is served
everywhere.
"""

from __future__ import annotations

from types import SimpleNamespace

from sugar_source_tree.construction_cache import AmbientVar

_DEPTH = AmbientVar("test_owner_reduction_depth", default=0)


def _owner():
    span = SimpleNamespace(start_line=1, start_col=0, end_line=2, end_col=0)
    return SimpleNamespace(
        unit=object(),
        kind="FunctionDef",
        reporter=object(),
        line_col_span=lambda: span,
    )


def test_a_reduction_that_reads_an_ambient_is_reduced_again_where_it_differs(
    monkeypatch,
) -> None:
    from sugar_lift_py_tests import tree_enumerate

    reduced: list = []

    def reduce(owner):
        reduced.append(_DEPTH.get())
        return ("outcome", reduced[-1])

    monkeypatch.setattr(tree_enumerate, "_OWNER_REDUCTIONS", {})
    monkeypatch.setattr(tree_enumerate, "function_universe_outcome", reduce)
    owner = _owner()

    first = tree_enumerate.owner_reduction(owner)
    assert tree_enumerate.owner_reduction(owner) is first

    token = _DEPTH.set(1)
    try:
        second = tree_enumerate.owner_reduction(owner)
        assert second is not first
        assert second.outcome == ("outcome", 1)
        assert tree_enumerate.owner_reduction(owner) is second
    finally:
        _DEPTH.reset(token)

    assert tree_enumerate.owner_reduction(owner) is first
    assert reduced == [0, 1]


def test_a_reduction_that_reads_no_ambient_is_served_everywhere(
    monkeypatch,
) -> None:
    from sugar_lift_py_tests import tree_enumerate

    reduced: list = []

    def reduce(owner):
        reduced.append(owner)
        return "outcome"

    monkeypatch.setattr(tree_enumerate, "_OWNER_REDUCTIONS", {})
    monkeypatch.setattr(tree_enumerate, "function_universe_outcome", reduce)
    owner = _owner()

    first = tree_enumerate.owner_reduction(owner)
    token = _DEPTH.set(1)
    try:
        assert tree_enumerate.owner_reduction(owner) is first
    finally:
        _DEPTH.reset(token)
    assert tree_enumerate.owner_reduction(owner) is first
    assert reduced == [owner]
