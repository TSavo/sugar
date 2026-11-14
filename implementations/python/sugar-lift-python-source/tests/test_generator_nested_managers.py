"""Nested ``@contextmanager`` generators build through the frame the call keeps.

Shape:

    @contextmanager
    def inner():
        prior = None
        yield 'inner'

    @contextmanager
    def outer():
        with inner():
            yield 'outer'

A same-module ``@contextmanager`` call keeps its own frame
(``call_applies_own_frame``, #7757): the frame is seated at the head and the
With is built as ``GeneratorWithSugar`` over it, the nested ``with inner()``
being one more statement of that frame.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar
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


def test_outer_generator_manager_builds_over_its_own_frame(tmp_path: Path) -> None:
    assert type(_consumer_with(tmp_path).sugar()) is GeneratorWithSugar
