"""A factory face the manager projection cannot read is not dropped.

``raises_chained_assignment_error`` returns ``nullcontext()`` under an
undecided flag and a ``@contextmanager`` generator manager otherwise. The
projection read the class-instance face and skipped the generator face, so
the construction claimed ``nullcontext`` on every path. Any face that returns
a value the projection does not read now makes the factory a named
``non-manager-result`` instead.
"""

from __future__ import annotations

from test_call_target_gap_mechanisms import _construct

from sugar_lift_python_source.manager_construction import (
    ConstructedManagerBehaviorV1,
    ManagerConstructionGapV1,
)

_PREFIX = (
    "from contextlib import contextmanager\n"
    "from arbitrary.flags import ENABLED\n\n"
    "class Quiet:\n"
    "    def __init__(self):\n"
    "        self.label = 7\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, *a):\n"
    "        return False\n\n"
    "@contextmanager\n"
    "def loud():\n"
    "    yield 7\n\n"
)
_FLAGS = "import platform\nENABLED = platform.python_implementation() == 'PyPy'\n"


def test_generator_face_beside_a_class_face_refuses(tmp_path):
    result = _construct(
        tmp_path,
        _PREFIX
        + "def make_guard(expected):\n"
        "    if ENABLED:\n"
        "        return Quiet()\n"
        "    return loud()\n",
        flags=_FLAGS,
    )
    assert isinstance(result, ManagerConstructionGapV1), result
    assert result.kind == "non-manager-result"
    assert "GeneratorConstructionV1" in result.detail


def test_class_faces_on_every_path_still_construct(tmp_path):
    result = _construct(
        tmp_path,
        _PREFIX
        + "def make_guard(expected):\n"
        "    if ENABLED:\n"
        "        return Quiet()\n"
        "    return Quiet()\n",
        flags=_FLAGS,
    )
    assert isinstance(result, ConstructedManagerBehaviorV1), result
