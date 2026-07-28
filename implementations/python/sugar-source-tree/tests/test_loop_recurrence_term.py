"""Canonical construction testimony for ``LoopRecurrenceSugar``."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.generator_construction import _generator_value_testimony
from sugar_lift_py_tests.ir import _term_content_cid, ctor, str_const
from sugar_lift_py_tests.loop_construction import LoopWireError
from sugar_lift_py_tests.outcome.resource_bindings import ManagerBinding
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


_OLD_TERM_CONSUMERS = (
    "GeneratorConstructionV1 payload testimony",
    "ManagerBinding fact testimony",
)


def _old_loop_term(loop):
    """The pre-occurrence term shape replaced by ConstructedTermSugar."""
    root = loop.construction.wire_graph()["root"]
    return ctor(
        "python:loop-recurrence-construction",
        (
            str_const(loop.target_cid),
            str_const(loop.loop_construction_cid),
            ctor(
                "python:loop-binding-coordinates",
                tuple(str_const(cid) for cid in loop.binding_coordinate_cids),
                symbol_kind="coordinate",
            ),
            ctor(
                "python:loop-outward-face-testimony",
                tuple(
                    str_const(cid) for cid in root["outwardHaltedFaceCids"]
                ),
                symbol_kind="coordinate",
            ),
        ),
        symbol_kind="coordinate",
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


def test_loop_term_occurrence_migration_reaches_every_existing_consumer(
    tmp_path: Path,
):
    """Old-vs-new identity changes are consumed opaquely at both live seats."""
    loop = _loop(tmp_path, _BASE, "migration.py")
    old_term = _old_loop_term(loop)
    new_term = loop.to_term(owner="migration")

    # Pinned schema migration: the authenticated occurrence is inserted after
    # target/construction identity; the remaining testimony is conserved.
    assert old_term != new_term
    assert new_term.args[:2] == old_term.args[:2]
    assert new_term.args[2] == loop.occurrence_term(owner="migration")
    assert new_term.args[3:] == old_term.args[2:]

    observed_consumers = []

    generator_testimony = _generator_value_testimony(
        loop, owner="LoopRecurrence migration"
    )
    assert generator_testimony == {
        "kind": "term-cid",
        "contentCid": _term_content_cid(new_term),
    }
    assert generator_testimony["contentCid"] != _term_content_cid(old_term)
    observed_consumers.append("GeneratorConstructionV1 payload testimony")

    (manager_fact,) = ManagerBinding("loop-manager", loop).to_facts()
    assert manager_fact.formula.args[1] == new_term
    assert manager_fact.formula.args[1] != old_term
    observed_consumers.append("ManagerBinding fact testimony")

    assert tuple(observed_consumers) == _OLD_TERM_CONSUMERS
