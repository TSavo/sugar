"""Canonical construction testimony for ``LoopRecurrenceSugar``."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.loop_construction import LoopWireError
from sugar_source_tree.tree import SourceFile


def _loop(tmp_path: Path, source: str, name: str):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    function = next(SourceFile(path_source(path)).functions()).sugar()
    return next(
        statement
        for statement in function.statements
        if type(statement).__name__ == "LoopRecurrenceSugar"
    )


_BASE = (
    "def exercise(xs):\n"
    "    for item in xs:\n"
    "        pass\n"
    "    return xs\n"
)


def test_identical_loop_construction_preimages_yield_identical_terms(tmp_path: Path):
    first = _loop(tmp_path, _BASE, "first.py")
    second = _loop(tmp_path, _BASE, "second.py")

    assert first.to_term(owner="test") == second.to_term(owner="test")


@pytest.mark.parametrize(
    "changed",
    (
        _BASE.replace("item", "member"),
        "\n" + _BASE,
        _BASE.replace("        pass\n", "        raise ValueError\n"),
    ),
    ids=("target", "coordinate", "outward-testimony"),
)
def test_changed_authenticated_loop_construction_changes_term(
    tmp_path: Path, changed: str
):
    baseline = _loop(tmp_path, _BASE, "baseline.py")
    variant = _loop(tmp_path, changed, "variant.py")

    assert baseline.to_term(owner="test") != variant.to_term(owner="test")


def test_tampered_loop_construction_refuses_term_projection(tmp_path: Path):
    loop = _loop(tmp_path, _BASE, "tampered.py")
    graph = deepcopy(loop.construction.wire_graph())
    graph["root"]["outwardHaltedFaceCids"].append("blake3-512:" + "f" * 128)
    tampered_construction = replace(loop.construction, _graph=graph)

    with pytest.raises(LoopWireError, match="loopConstructionCid mismatch"):
        replace(loop, construction=tampered_construction).to_term(owner="test")
