"""Loop-carried bindings advance per iteration and halt at the live snapshot."""

from __future__ import annotations

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.outcome import Halted
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())


def test_concrete_loop_rebinds_carried_value_each_iteration() -> None:
    post = (
        _function(
            "def arbitrary():\n"
            "    carried = 0\n"
            "    for item in (1, 2, 3):\n"
            "        carried = carried + item\n"
            "    return carried\n"
        )
        .sugar()
        .desugar()
        .value.post()
    )
    assert post.args[1].value == 6


def test_mid_iteration_halt_retains_exact_pre_halt_binding_snapshot() -> None:
    constructed = _function(
        "def arbitrary(limit, stop):\n"
        "    carried = 0\n"
        "    while carried < limit:\n"
        "        carried = carried + 1\n"
        "        if carried == stop:\n"
        "            raise ValueError(carried)\n"
        "        carried = 99\n"
        "    return carried\n"
    ).sugar()

    loop = constructed.statements[1]
    assert len(loop.outward_faces) == 1
    snapshot = loop.outward_faces[0].state
    assert len(snapshot) == 1
    assert "carried + 1" in snapshot[0].state.segment()
    assert "99" not in snapshot[0].state.segment()

    exits = loop.desugar()
    halted = next(exit_ for exit_ in exits.exits if isinstance(exit_, Halted))
    assert halted.state is snapshot
