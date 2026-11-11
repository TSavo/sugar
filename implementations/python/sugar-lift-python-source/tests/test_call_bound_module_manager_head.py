"""A ``with`` over a chain on a module a call returned is cited (#7742).

``pandas.io.common._get_binary_io_classes`` reads::

    zstd = import_optional_dependency("zstandard", errors="ignore")
    if zstd is not None:
        with zstd.ZstdDecompressor().stream_reader(b"") as reader:
            ...

``importlib.import_module`` of a present top-level module completes with that
module, ``python:module(<name>)`` (the object ``import <name>`` binds), so the
helper's return arms are that module or ``None``.  zstandard is installed but
off the enrolled population (and implemented in C), so the manager its chain
produces is cited over ``OpaqueCitedContextManagerRefV1`` naming
``python:zstandard.ZstdDecompressor``: enter and exit may raise, a body raise
still propagates.  A helper that returns something that is not a module, an
absent module, and a local bound twice are never cited.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    OpaqueCitedContextManagerRefV1,
    SourceFragmentCoordinateV1,
)
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.source_call_resolution import (
    imported_module_value,
    module_value_name,
    pinned_present_top_level_module,
)
from sugar_lift_py_tests.sugar.with_opaque_cited_manager_sugar import (
    WithOpaqueCitedManagerSugar,
)
from sugar_source_tree.formal_manager_head import call_bound_local_manager_head
from sugar_source_tree.nodes import With
from sugar_source_tree.panic import SourceTreePanic

from test_contextlib_suppress_source_exit_faces import _corpus, _open


def _function_rows(source_file, with_node):
    """``(With consumer type, sorted rows f leaves by)``; a halt's row names
    its exception, or None when the effect names none."""
    from sugar_lift_py_tests.outcome import Halted, outcome_to_exitset
    from sugar_source_tree.nodes import FunctionDef

    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    rows = set()
    for face in outcome_to_exitset(func.sugar().desugar()).exits:
        if isinstance(face, Halted):
            rows.add(("halt", getattr(face.effect, "exception_name", None)))
            continue
        for entry in getattr(getattr(face.value, "record", None), "statements", ()):
            name = type(entry).__name__
            if name in ("ReturnValue", "GuardedReturn") and "value=7)" in repr(
                entry.value
            ):
                rows.add(("return", 7))
            elif name == "Incomplete":
                rows.add(("halt", getattr(entry.effect, "exception_name", None)))
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
    (item,) = with_node.items
    coordinate = SourceFragmentCoordinateV1(
        with_node.unit.source_cid, *item._manager_use_site_span()
    )
    seated = with_node.unit.construction_context.source_derived_contract_refs.get(
        coordinate
    )
    return source_file, with_node, seated


def test_a_chain_on_a_returned_off_population_module_is_cited(tmp_path):
    source_file, with_node, seated = _lifted(tmp_path)
    assert type(seated) is OpaqueCitedContextManagerRefV1
    assert seated.target_name == "python:zstandard.ZstdDecompressor"
    assert seated.roster.resolution_kind == "call-target-off-population"
    consumer, rows = _function_rows(source_file, with_node)
    assert consumer is WithOpaqueCitedManagerSugar
    # The head, enter and exit may each raise; the body falls through.
    assert ("halt", None) in rows
    assert ("return", 7) in rows


def test_the_cited_with_keeps_the_body_raise(tmp_path):
    source_file, with_node, seated = _lifted(tmp_path, body="raise KeyError(1)")
    assert type(seated) is OpaqueCitedContextManagerRefV1
    _consumer, rows = _function_rows(source_file, with_node)
    assert ("halt", "KeyError") in rows


def test_a_present_module_is_its_module_coordinate():
    assert pinned_present_top_level_module("zstandard")
    assert pinned_present_top_level_module("json")
    assert not pinned_present_top_level_module("zz_sugar_absent_module_7742")
    assert not pinned_present_top_level_module("os.path")  # dotted: not asked
    assert module_value_name(imported_module_value("zstandard")) == "zstandard"
    # Nothing else is read as a module.
    assert module_value_name(NoneValue()) is None


def test_a_returned_value_that_is_not_a_module_is_not_cited(tmp_path):
    # The lying twin: the helper returns its string operand, not a module.
    _source_file, _with_node, seated = _lifted(tmp_path, returned="name")
    assert not isinstance(seated, OpaqueCitedContextManagerRefV1)
    (tmp_path / "again").mkdir()
    source_file, with_node, _ = _lifted(tmp_path / "again", returned="name")
    with pytest.raises(SourceTreePanic, match="CONTEXT MANAGER RESOLUTION GAP"):
        _function_rows(source_file, with_node)


def test_an_absent_module_is_never_cited(tmp_path):
    # import_module halts with ModuleNotFoundError, so opt returns only None:
    # nothing is a module and nothing is cited.  That the suite is then dead
    # is test_absent_optional_module_branch's (#7697).
    _source_file, _with_node, seated = _lifted(
        tmp_path, name="zz_sugar_absent_module_7742"
    )
    assert not isinstance(seated, OpaqueCitedContextManagerRefV1)


def test_only_a_local_bound_once_by_a_call_qualifies():
    def head(source, line):
        return call_bound_local_manager_head(source, line, 9)

    once = "def f():\n    z = g('m')\n    with z.A().b(1):\n        pass\n"
    assert head(once, 3) == ((2, 8), "A")
    # Bound twice, bound by a non-call, a parameter, or no attribute on it.
    assert head("def f():\n    z = g('m')\n    z = g('n')\n    with z.A():\n        pass\n", 4) is None
    assert head("def f(m):\n    z = m\n    with z.A():\n        pass\n", 3) is None
    assert head("def f(z):\n    with z.A():\n        pass\n", 2) is None
    assert head("def f():\n    z = g('m')\n    with z():\n        pass\n", 3) is None


def test_a_returned_off_population_stdlib_module_is_cited(tmp_path):
    # Pair (population), truthful: json is not enrolled here.
    _source_file, _with_node, seated = _lifted(tmp_path, name="json")
    assert type(seated) is OpaqueCitedContextManagerRefV1
    assert seated.target_name == "python:json.ZstdDecompressor"


def test_a_returned_enrolled_module_is_not_cited(tmp_path):
    # Pair (population), lying: the same chain on contextlib, which this
    # session enrolls: a module on the population is never cited.
    _source_file, _with_node, seated = _lifted(tmp_path, name="contextlib")
    assert not isinstance(seated, OpaqueCitedContextManagerRefV1)
