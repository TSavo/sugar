"""A ``with`` whose manager cannot be read from source is undecided, not refused.

The owner's rule (#7661): you install what you have and you cite what you
don't.  Two heads have nothing to read:

* ``klass = getattr(module, name)`` then ``with klass(path) as f:`` -- a
  run-time string picks the class, so there is no callee
  (``tests/io/parser/test_python_parser_only.py:176``).
* ``with mmap.mmap(fd, 0) as m:`` -- no artifact authenticates ``mmap``, so
  the lifter does not have the callee: it is not bridged
  (``tests/io/parser/test_c_parser_only.py:560``), the same as
  ``tarfile.open``, an unenrolled pure-Python callee.

Each manager is what its head reduces to (#7757), and nothing decides it:
it is the undecided manager (``WithReducedManagerSugar``): enter and exit may
each raise, suppression is undecided, and a raise in the body still
propagates.  A source class at the head runs its own methods, and a source
class lacking them raises the interpreter's TypeError.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
    WithReducedManagerSugar,
)
from sugar_source_tree.nodes import With

from test_contextlib_suppress_source_exit_faces import _corpus, _open
from test_contextmanager_generator_protocol import _function_rows

_GETATTR_HEAD = (
    "def f(module, name):\n"
    "    klass = getattr(module, name)\n"
    "    with klass(1) as tmp:\n"
    "        {body}\n"
    "    return 7\n"
)
_C_TYPE_HEAD = (
    "import mmap\n"
    "def f(fd):\n"
    "    with mmap.mmap(fd, 0) as m:\n"
    "        {body}\n"
    "    return 7\n"
)
_PYTHON_OFF_POPULATION_HEAD = (
    "import tarfile\n"
    "def f(fd):\n"
    "    with tarfile.open(fd) as m:\n"
    "        {body}\n"
    "    return 7\n"
)
_SOURCE_CLASS_HEAD = (
    "class CM:\n"
    "    def __enter__(self):\n"
    "        return 1\n"
    "    def __exit__(self, *exc):\n"
    "        return False\n"
    "def f():\n"
    "    with CM():\n"
    "        {body}\n"
    "    return 7\n"
)


def _lifted(tmp_path: Path, template: str, body: str):
    """``(With consumer type, sorted return/halt rows of f)``."""
    source_file = _open(_corpus(tmp_path, template.format(body=body)))
    (with_node,) = [n for n in source_file.nodes() if isinstance(n, With)]
    return _function_rows(source_file, with_node)


def test_run_time_selected_head_is_undecided(tmp_path):
    consumer, rows = _lifted(tmp_path, _GETATTR_HEAD, "pass")
    assert consumer is WithReducedManagerSugar
    # The head call, enter and exit may each raise; the body falls through.
    assert ("halt", None) in rows
    assert ("return", 7) in rows


def test_run_time_selected_head_keeps_the_body_raise(tmp_path):
    _consumer, rows = _lifted(tmp_path, _GETATTR_HEAD, "raise KeyError(1)")
    assert ("halt", "KeyError") in rows


def test_an_unauthenticated_callee_is_undecided(tmp_path):
    consumer, rows = _lifted(tmp_path, _C_TYPE_HEAD, "pass")
    assert consumer is WithReducedManagerSugar
    assert ("halt", None) in rows
    assert ("return", 7) in rows


def test_not_bridged_does_not_depend_on_the_callee_language(tmp_path):
    # A pure-Python callee the lifter does not have (stdlib ``tarfile``, off
    # the enrolled population) and one no artifact authenticates (``mmap``)
    # get the same consumer and the same rows.
    (tmp_path / "c").mkdir()
    (tmp_path / "py").mkdir()
    c_consumer, c_rows = _lifted(tmp_path / "c", _C_TYPE_HEAD, "pass")
    py_consumer, py_rows = _lifted(
        tmp_path / "py", _PYTHON_OFF_POPULATION_HEAD, "pass"
    )
    assert py_consumer is c_consumer is WithReducedManagerSugar
    assert py_rows == c_rows


def test_an_unauthenticated_callee_keeps_the_body_raise(tmp_path):
    _consumer, rows = _lifted(tmp_path, _C_TYPE_HEAD, "raise KeyError(1)")
    assert ("halt", "KeyError") in rows


def test_a_readable_source_manager_runs_its_own_methods(tmp_path):
    # The lying twin: a source class at the head enters and exits through
    # its own methods, read at reduce on the head's value.
    consumer, rows = _lifted(tmp_path, _SOURCE_CLASS_HEAD, "pass")
    assert consumer is WithReducedManagerSugar
    # Its enter and exit are its own source: neither may raise.
    assert rows == [("return", 7)]


def test_a_source_class_without_the_protocol_raises_type_error(tmp_path):
    # A class whose own type lacks ``__enter__`` raises the interpreter's
    # TypeError at the head, never a manager.
    template = (
        "class N:\n"
        "    pass\n"
        "def f():\n"
        "    with N():\n"
        "        {body}\n"
        "    return 7\n"
    )
    _consumer, rows = _lifted(tmp_path, template, "pass")
    assert ("halt", "TypeError") in rows
    assert ("return", 7) not in rows


_NOT_BRIDGED_HEADS = {
    # ``_decimal`` holds no source in any artifact.
    "decimal.localcontext": ("import decimal\n", "decimal.localcontext()"),
    # ``io.StringIO`` is ``_io.StringIO``: no source in any artifact.
    "io.StringIO": ("import io\n", "io.StringIO()"),
    # A builtin name the module never binds: ``builtins`` has no artifact.
    "open": ("", "open(fd)"),
}


@pytest.mark.parametrize("head", sorted(_NOT_BRIDGED_HEADS))
def test_a_head_with_no_source_is_undecided(tmp_path, head):
    prelude, call = _NOT_BRIDGED_HEADS[head]
    template = (
        prelude
        + "def f(fd):\n"
        + f"    with {call} as m:\n"
        + "        {body}\n"
        + "    return 7\n"
    )
    consumer, rows = _lifted(tmp_path, template, "pass")
    assert consumer is WithReducedManagerSugar
    assert ("halt", None) in rows
    assert ("return", 7) in rows
