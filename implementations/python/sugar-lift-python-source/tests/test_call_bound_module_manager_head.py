"""A ``with`` over a chain on a module a call returned (#7742).

``pandas.io.common._get_binary_io_classes`` reads::

    zstd = import_optional_dependency("zstandard", errors="ignore")
    if zstd is not None:
        with zstd.ZstdDecompressor().stream_reader(b"") as reader:
            ...

``importlib.import_module`` of a present top-level module completes with that
module, ``python:module(<name>)`` (the object ``import <name>`` binds), so the
helper's return arms are that module or ``None``.  zstandard is installed but
off the enrolled population (and implemented in C), so the manager its chain
produces is what the head reduces to: nothing decides it, so enter and exit
may raise, and a body raise still propagates.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.source_call_resolution import (
    imported_module_value,
    pinned_present_top_level_module,
)
from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
    WithReducedManagerSugar,
)
from sugar_source_tree.nodes import With

from test_contextlib_suppress_source_exit_faces import _corpus, _open


def _function_rows(source_file, with_node):
    """``(With consumer type, sorted rows f leaves by)``; a halt's row names
    its exception, or None when the effect names none."""
    from sugar_lift_py_tests.outcome import ExitSet, Halted
    from sugar_source_tree.nodes import FunctionDef

    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    rows = set()
    for face in func.sugar().desugar().exits:
        if isinstance(face, Halted):
            rows.add(("halt", getattr(face.effect, "exception_name", None)))
            continue
        for entry in getattr(getattr(face.value, "record", None), "statements", ()):
            name = type(entry).__name__
            if name in ("ReturnValue", "GuardedReturn") and "value=7)" in repr(
                entry.value
            ):
                rows.add(("return", 7))
            elif isinstance(entry, ExitSet) and entry.halts() == entry.exits:
                for halt in entry.halts():
                    rows.add(("halt", getattr(halt.effect, "exception_name", None)))
    return type(with_node.sugar()), sorted(rows, key=repr)

_OPT = (
    "import importlib\n"
    "def opt(name):\n"
    "    try:\n"
    "        module = importlib.import_module(name)\n"
    "    except ImportError:\n"
    "        return None\n"
    "    return {returned}\n"
    "def f():\n"
    "    z = opt({name!r})\n"
    "    if z is not None:\n"
    "        with z.ZstdDecompressor().stream_reader(b'') as reader:\n"
    "            {body}\n"
    "    return 7\n"
)


def _lifted(tmp_path: Path, *, name="zstandard", returned="module", body="pass"):
    source = _OPT.format(name=name, returned=returned, body=body)
    source_file = _open(_corpus(tmp_path, source))
    (with_node,) = [n for n in source_file.nodes() if isinstance(n, With)]
    return source_file, with_node


def test_a_chain_on_a_returned_off_population_module_is_undecided(tmp_path):
    """The head reduces to an attribute chain on the off-population module:
    nothing decides the manager, so it is the undecided manager (#7757)."""
    source_file, with_node = _lifted(tmp_path)
    consumer, rows = _function_rows(source_file, with_node)
    assert consumer is WithReducedManagerSugar
    # The head, enter and exit may each raise; the body falls through.
    assert ("halt", None) in rows
    assert ("return", 7) in rows


def test_the_undecided_with_keeps_the_body_raise(tmp_path):
    source_file, with_node = _lifted(tmp_path, body="raise KeyError(1)")
    _consumer, rows = _function_rows(source_file, with_node)
    assert ("halt", "KeyError") in rows


def test_a_present_module_is_its_module_coordinate():
    # Asked of a module every pinned interpreter holds (``json``): whether
    # ``zstandard`` is installed is the runner's environment, not the law.
    assert pinned_present_top_level_module("json")
    assert not pinned_present_top_level_module("zz_sugar_absent_module_7742")
    assert not pinned_present_top_level_module("os.path")  # dotted: not asked
    assert imported_module_value("json").term == ctor(
        "python:module", (str_const("json"),)
    )
