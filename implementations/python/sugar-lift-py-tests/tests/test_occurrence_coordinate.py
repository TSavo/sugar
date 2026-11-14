"""#7808 (B′): a call's occurrence is its source coordinate, never a repr.

``python:call_result`` and ``python:unknown_callee_call`` name the evaluation
they stand for by ``python:occurrence(<site coordinate CID>, <path>…)``, and a
callee frame's path segment is ``call:<site coordinate CID>``. The coordinate
is ``SourceFragmentCoordinateV1`` (source CID plus line/col span): the same on
every mint and every machine. A fragment's repr embedded ``unit.filename``,
which is not guaranteed relative.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests import lift_rpc
from sugar_lift_py_tests import tree_enumerate as _tree
from sugar_lift_py_tests.caller_parameter_contract import source_coordinate
from sugar_lift_py_tests.occurrence import (
    call_frame_path,
    occurrence_path,
    occurrence_term,
    site_coordinate_cid,
)

_SOURCE = "def test_h():\n    assert h() == 3\n"


def _call_fragment(root: Path):
    from sugar_source_tree.nodes import Call

    path = root / "m.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_SOURCE, encoding="utf-8")
    tree = lift_rpc._open_enumerated_file(path, root=root, locus_root=root)
    (fn,) = tuple(tree.functions())
    (call,) = [node for node in fn.walk() if isinstance(node, Call)]
    return tree, fn, call.fragment


def test_the_coordinate_cid_is_the_same_at_two_roots(tmp_path: Path) -> None:
    _t1, _f1, here = _call_fragment(tmp_path / "one")
    _t2, _f2, there = _call_fragment(tmp_path / "elsewhere" / "deeper")
    assert site_coordinate_cid(here) == site_coordinate_cid(there)
    assert site_coordinate_cid(here) == source_coordinate(here).cid
    assert site_coordinate_cid(here).startswith("blake3-512:")


def test_an_occurrence_term_carries_no_repr_and_no_path(tmp_path: Path) -> None:
    _tree_, _fn, site = _call_fragment(tmp_path / "root")
    spelled = repr(occurrence_term(site, ()))
    assert "SourceFragment" not in spelled
    assert str(tmp_path) not in spelled
    assert site_coordinate_cid(site) in spelled


def test_a_callee_frame_segment_is_the_coordinate_cid(tmp_path: Path) -> None:
    _tree_, _fn, site = _call_fragment(tmp_path / "root")
    (segment,) = call_frame_path(site, ())
    assert segment == f"call:{site_coordinate_cid(site)}"
    with occurrence_path((segment,)):
        nested = repr(occurrence_term(site))
    assert "SourceFragment" not in nested
    assert segment in nested


def test_a_site_with_no_coordinate_is_refused_by_name() -> None:
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic, match="no source coordinate"):
        site_coordinate_cid(None)


def _subtree(nodes: dict, cid: str) -> list:
    """Every term node under ``cid`` in a term table, following term-refs."""
    out, todo = [], [cid]
    while todo:
        node = nodes[todo.pop()]
        out.append(node)
        todo.extend(
            arg["cid"]
            for arg in node.get("args", ())
            if isinstance(arg, dict) and arg.get("kind") == "term-ref"
        )
    return out


def test_an_unknown_callee_row_names_its_call_by_coordinate(tmp_path: Path) -> None:
    """The call terms carry the coordinate and no repr. Other site-keyed
    atoms (here the ``==``) keep ``str(site)``: listed on #7808, not B′."""
    from sugar_lift_py_tests.ir import TermTableBuilder

    _tree_, fn, site = _call_fragment(tmp_path / "root")
    _memento, rows = _tree.function_contract_rows(fn, "m.py")
    table = TermTableBuilder()
    for row in rows or []:
        row.to_rpc_with_term_table(table)
    calls = [
        cid
        for cid, node in table.nodes.items()
        if node.get("name") in ("python:call_result", "python:unknown_callee_call")
    ]
    assert calls, "the unknown callee's terms reached the rows"
    for cid in calls:
        spelled = json.dumps(_subtree(table.nodes, cid))
        assert "python:occurrence" in spelled
        assert site_coordinate_cid(site) in spelled
        assert "SourceFragment" not in spelled
        assert str(tmp_path) not in spelled
