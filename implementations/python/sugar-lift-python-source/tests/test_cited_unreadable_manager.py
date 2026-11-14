"""A ``with`` whose manager cannot be read from source is cited, not refused.

The owner's rule (#7661): you install what you have and you cite what you
don't.  Two heads have nothing to read:

* ``klass = getattr(module, name)`` then ``with klass(path) as f:`` -- a
  run-time string picks the class, so there is no callee
  (``tests/io/parser/test_python_parser_only.py:176``).  The citation names no
  callee, only the head's own coordinate and ``head-runtime-selected``.
* ``with mmap.mmap(fd, 0) as m:`` -- no artifact authenticates ``mmap``, so
  the lifter does not have the callee: it is not bridged
  (``tests/io/parser/test_c_parser_only.py:560``).  The citation names the
  callee's import target and nothing about why it is not bridged: the same
  kind as ``tarfile.open``, an unenrolled pure-Python callee.

Both are constructed over the existing ``OpaqueCitedContextManagerRefV1``
(``WithOpaqueCitedManagerSugar``): enter and exit may each raise, suppression
is undecided, and a raise in the body still propagates.  A manager whose
source CAN be read is still constructed from source, and a head proven not to
be a manager still refuses through its own door.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    OpaqueCitedContextManagerRefV1,
    SourceFragmentCoordinateV1,
)
from sugar_lift_py_tests.sugar.with_opaque_cited_manager_sugar import (
    WithOpaqueCitedManagerSugar,
)
from sugar_source_tree.formal_manager_head import runtime_selected_manager_head
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
    """``(seated ref, With consumer type, sorted return/halt rows of f)``."""
    source_file = _open(_corpus(tmp_path, template.format(body=body)))
    (with_node,) = [n for n in source_file.nodes() if isinstance(n, With)]
    (item,) = with_node.items
    coordinate = SourceFragmentCoordinateV1(
        with_node.unit.source_cid, *item._manager_use_site_span()
    )
    seated = with_node.unit.construction_context.source_derived_contract_refs.get(
        coordinate
    )
    consumer, rows = _function_rows(source_file, with_node)
    return seated, consumer, rows


def test_run_time_selected_head_is_cited_naming_its_own_site(tmp_path):
    seated, consumer, rows = _lifted(tmp_path, _GETATTR_HEAD, "pass")
    assert type(seated) is OpaqueCitedContextManagerRefV1
    # No callee is named: there is none.  The subject is the head's site.
    assert seated.target_name == ""
    assert seated.roster.resolution_kind == "head-runtime-selected"
    assert seated.use_site.start_line == 3
    assert "head-runtime-selected head at" in seated.cited_subject
    assert consumer is WithOpaqueCitedManagerSugar
    # The head call, enter and exit may each raise; the body falls through.
    assert ("halt", None) in rows
    assert ("return", 7) in rows


def test_run_time_selected_head_keeps_the_body_raise(tmp_path):
    seated, _consumer, rows = _lifted(tmp_path, _GETATTR_HEAD, "raise KeyError(1)")
    assert type(seated) is OpaqueCitedContextManagerRefV1
    assert ("halt", "KeyError") in rows


def test_an_unauthenticated_callee_is_cited_as_not_bridged(tmp_path):
    seated, consumer, rows = _lifted(tmp_path, _C_TYPE_HEAD, "pass")
    assert type(seated) is OpaqueCitedContextManagerRefV1
    assert seated.target_name == "python:mmap.mmap"
    assert seated.roster.resolution_kind == "call-target-off-population"
    assert consumer is WithOpaqueCitedManagerSugar
    assert ("halt", None) in rows
    assert ("return", 7) in rows


def test_not_bridged_does_not_depend_on_the_callee_language(tmp_path):
    # A pure-Python callee the lifter does not have (stdlib ``tarfile``, off
    # the enrolled population) and one no artifact authenticates (``mmap``)
    # get the same citation kind, the same consumer and the same rows.
    (tmp_path / "c").mkdir()
    (tmp_path / "py").mkdir()
    c_seated, c_consumer, c_rows = _lifted(tmp_path / "c", _C_TYPE_HEAD, "pass")
    py_seated, py_consumer, py_rows = _lifted(
        tmp_path / "py", _PYTHON_OFF_POPULATION_HEAD, "pass"
    )
    assert type(py_seated) is type(c_seated) is OpaqueCitedContextManagerRefV1
    assert py_seated.target_name == "python:tarfile.open"
    assert (
        py_seated.roster.resolution_kind
        == c_seated.roster.resolution_kind
        == "call-target-off-population"
    )
    assert py_consumer is c_consumer is WithOpaqueCitedManagerSugar
    assert py_rows == c_rows


def test_an_unauthenticated_callee_keeps_the_body_raise(tmp_path):
    seated, _consumer, rows = _lifted(tmp_path, _C_TYPE_HEAD, "raise KeyError(1)")
    assert type(seated) is OpaqueCitedContextManagerRefV1
    assert ("halt", "KeyError") in rows


def test_a_readable_source_manager_is_constructed_not_cited(tmp_path):
    # The lying twin: a manager whose source can be read is never cited.
    seated, consumer, rows = _lifted(tmp_path, _SOURCE_CLASS_HEAD, "pass")
    assert seated is not None
    assert not isinstance(seated, OpaqueCitedContextManagerRefV1)
    assert consumer is not WithOpaqueCitedManagerSugar
    # Its enter and exit are read from source: neither may raise.
    assert rows == [("return", 7)]


def test_a_proven_non_manager_head_is_not_cited(tmp_path):
    # The lying twin of a non-manager: a class proven from source to lack
    # ``__enter__`` keeps its refusal face (TypeError), never a citation.
    template = (
        "class N:\n"
        "    pass\n"
        "def f():\n"
        "    with N():\n"
        "        {body}\n"
        "    return 7\n"
    )
    seated, consumer, rows = _lifted(tmp_path, template, "pass")
    assert not isinstance(seated, OpaqueCitedContextManagerRefV1)
    assert consumer is not WithOpaqueCitedManagerSugar
    assert ("return", 7) not in rows


def _unit(source: str):
    """The typed unit of ``source``: the head reader asks it how names bind."""
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.tree import SourceFile

    return SourceFile(
        (source, "e.py", blake3_512_of(source.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    ).unit


def test_only_a_run_time_string_selection_qualifies():
    def head(source, line=3):
        return runtime_selected_manager_head(_unit(source), line, 9)

    picked = "def f(m, n):\n    k = getattr(m, n)\n    with k(1):\n        pass\n"
    assert head(picked) == "k(1)"
    # A constant attribute name is a known attribute, read through its owner.
    assert head("def f(m):\n    k = getattr(m, 'A')\n    with k(1):\n        pass\n") is None
    # Bound from anything else, or bound twice, or after the with.
    assert head("def f(m):\n    k = make(m)\n    with k(1):\n        pass\n") is None
    assert (
        head("def f(m, n):\n    k = getattr(m, n)\n    with k(1):\n        pass\n    k = 2\n")
        is None
    )
    assert head("def f(m, n):\n    with k(1):\n        pass\n    k = getattr(m, n)\n", 2) is None
    # A module that binds its own ``getattr`` is not the builtin.
    assert head("getattr = g\n" + picked, 4) is None
    # Nor is a function's own ``getattr`` parameter: the binding decides, not
    # the spelling.
    assert (
        head("def f(m, n, getattr):\n    k = getattr(m, n)\n    with k(1):\n        pass\n")
        is None
    )


_NOT_BRIDGED_HEADS = {
    # ``_decimal`` holds no source in any artifact.
    "decimal.localcontext": ("import decimal\n", "decimal.localcontext()"),
    # ``io.StringIO`` is ``_io.StringIO``: no source in any artifact.
    "io.StringIO": ("import io\n", "io.StringIO()"),
    # A builtin name the module never binds: ``builtins`` has no artifact.
    "open": ("", "open(fd)"),
}


@pytest.mark.parametrize("head", sorted(_NOT_BRIDGED_HEADS))
def test_a_head_with_no_source_is_cited_as_not_bridged(tmp_path, head):
    prelude, call = _NOT_BRIDGED_HEADS[head]
    template = (
        prelude
        + "def f(fd):\n"
        + f"    with {call} as m:\n"
        + "        {body}\n"
        + "    return 7\n"
    )
    seated, consumer, rows = _lifted(tmp_path, template, "pass")
    assert type(seated) is OpaqueCitedContextManagerRefV1
    assert seated.roster.resolution_kind == "call-target-off-population"
    assert consumer is WithOpaqueCitedManagerSugar
    assert ("halt", None) in rows
    assert ("return", 7) in rows
