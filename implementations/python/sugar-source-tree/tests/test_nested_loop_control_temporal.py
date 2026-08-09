"""Nested loop controls are consumed only by their authenticated target loop."""

from __future__ import annotations

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())


def _returned_int(source: str) -> int:
    return _function(source).sugar().desugar().value.post().args[1].value


def test_inner_break_preserves_outer_state_and_does_not_suppress_outer_else() -> None:
    assert (
        _returned_int(
            "def arbitrary():\n"
            "    carried = 0\n"
            "    for outer in (0, 1):\n"
            "        carried = carried + 10\n"
            "        for inner in (0, 1):\n"
            "            carried = carried + 1\n"
            "            break\n"
            "    else:\n"
            "        carried = carried + 100\n"
            "    return carried\n"
        )
        == 122
    )


def test_inner_continue_preserves_iteration_state_before_outer_tail() -> None:
    assert (
        _returned_int(
            "def arbitrary():\n"
            "    carried = 0\n"
            "    for outer in (0, 1):\n"
            "        for inner in (0, 1):\n"
            "            carried = carried + 1\n"
            "            continue\n"
            "        carried = carried + 10\n"
            "    else:\n"
            "        carried = carried + 100\n"
            "    return carried\n"
        )
        == 124
    )


def test_inner_and_outer_controls_mint_distinct_target_coordinates() -> None:
    function = _function(
        "def arbitrary(values):\n"
        "    for outer in values:\n"
        "        for inner in values:\n"
        "            break\n"
        "        continue\n"
    )
    controls = [node for node in function.walk() if node.kind in {"Break", "Continue"}]
    targets = {node.kind: node.sugar().target_cid for node in controls}
    assert targets["Break"] != targets["Continue"]
