"""Nested ``@contextmanager`` generators: the call at the head is its edge.

Shape:

    @contextmanager
    def inner():
        prior = None
        yield 'inner'

    @contextmanager
    def outer():
        with inner():
            yield 'outer'

A same-module ``@contextmanager`` call has its frame seated by the callee's
name (``call_applies_own_frame``, #7757), and the call is the definition's
coordinate and edge (#7757 step 6): the With enters the value the head
reduced to (``WithReducedManagerSugar``), never ``outer``'s frame run to its
first yield.  Verdict moved: before, the With was ``GeneratorWithSugar``.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
    WithReducedManagerSugar,
)
from sugar_source_tree.nodes import With

import test_contextlib_suppress_source_exit_faces as opener
from test_contextlib_suppress_source_exit_faces import _corpus


_NESTED_CM = (
    "from contextlib import contextmanager\n"
    "\n"
    "@contextmanager\n"
    "def inner():\n"
    "    prior = None\n"
    "    yield 'inner'\n"
    "\n"
    "@contextmanager\n"
    "def outer():\n"
    "    with inner():\n"
    "        yield 'outer'\n"
    "\n"
    "def f():\n"
    "    with outer():\n"
    "        pass\n"
    "    return 7\n"
)


def _consumer_with(tmp_path: Path) -> With:
    source_file = opener._open(_corpus(tmp_path, _NESTED_CM))
    return next(
        node
        for node in source_file.nodes()
        if isinstance(node, With)
        and node.lineno == _NESTED_CM.splitlines().index("    with outer():") + 1
    )


def test_outer_generator_manager_head_is_its_edge(tmp_path: Path) -> None:
    assert type(_consumer_with(tmp_path).sugar()) is WithReducedManagerSugar
