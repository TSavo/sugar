"""Sorting the ``with`` heads refused as ``runtime-selected`` (#7732).

Three causes, each with its twins:

* A head that is the enter result of a manager a caller passed
  (``with c.builder.if_else(p) as (then, otherwise):`` then ``with then:``,
  ``core/_numba/extensions.py:362``): no frame knows the passed object's type,
  so nothing decides the manager.  It joins #7729's ``head-runtime-selected``
  citation.  When the outer manager is readable source, the inner head is NOT
  cited.
* Population projected a frame for its manager calls before any reader had
  seated a contract, and a ``with ... as`` in that frame demanded its contract
  then (``tests/io/parser/common/test_file_buffer_url.py:429``,
  ``io/xml.py:537``).  A ``with ... as name`` binds ``name`` without demanding
  a row nobody seated (``With.substitution_binding``), in the projection as
  everywhere; the With still constructs (or refuses) through the require door.
* A same-module ``@contextmanager`` whose body runs ``with open(...)``
  (``io/formats/format.py:1052``) built its frame before ``open`` was seated.
  The one ``with`` reader reads a definition's own ``with`` nodes before the
  definition (``_WithReader.read_within``); ``open`` is the builtin name
  (``SourceUnit.builtin_reference_at``), cited.
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
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_source_tree.formal_manager_head import runtime_selected_manager_head
from sugar_source_tree.nodes import With
from sugar_source_tree.panic import SourceTreePanic

from test_cited_unreadable_manager import _unit
from test_contextlib_suppress_source_exit_faces import _corpus, _open
from test_contextmanager_generator_protocol import _function_rows


def _seated(tmp_path: Path, source: str):
    """``(source_file, {start_line: seated row type name or None})``."""
    source_file = _open(_corpus(tmp_path, source))
    seated = {}
    for with_node in [n for n in source_file.nodes() if isinstance(n, With)]:
        refs = with_node.unit.construction_context.source_derived_contract_refs
        for item in with_node.items:
            coordinate = SourceFragmentCoordinateV1(
                with_node.unit.source_cid, *item._manager_use_site_span()
            )
            seated[coordinate.start_line] = refs.get(coordinate)
    return source_file, seated


_FORMAL_ENTER_RESULT = (
    "def f(c, p):\n"
    "    with c.builder.if_else(p) as then:\n"
    "        with then:\n"
    "            {body}\n"
    "    return 7\n"
)


def test_formal_enter_result_head_is_cited_naming_its_own_site(tmp_path):
    source_file, seated = _seated(tmp_path, _FORMAL_ENTER_RESULT.format(body="pass"))
    inner = seated[3]
    assert type(inner) is OpaqueCitedContextManagerRefV1
    assert inner.target_name == ""
    assert inner.roster.resolution_kind == "head-runtime-selected"
    assert inner.use_site.start_line == 3
    with_node = [n for n in source_file.nodes() if isinstance(n, With)][1]
    assert type(with_node.sugar()) is WithOpaqueCitedManagerSugar


def test_formal_enter_result_head_desugars_to_a_named_stop(tmp_path):
    # The next stop, stated rather than hidden: reducing the cited manager's
    # enter over an enter-result head refuses loudly in the RuntimeEffect
    # floor (its operand is an effect slot), never a silent completion.
    source_file, seated = _seated(
        tmp_path, _FORMAL_ENTER_RESULT.format(body="raise KeyError(1)")
    )
    assert type(seated[3]) is OpaqueCitedContextManagerRefV1
    with_node = [n for n in source_file.nodes() if isinstance(n, With)][1]
    with pytest.raises(ConstructionPanic, match="RuntimeEffect"):
        _function_rows(source_file, with_node)


def test_enter_result_of_a_readable_source_manager_is_not_cited(tmp_path):
    # The lying twin: the outer manager is a class read from source, so its
    # enter result is readable and the inner head must never be cited.
    source = (
        "class CM:\n"
        "    def __enter__(self):\n"
        "        return (1, 2)\n"
        "    def __exit__(self, *exc):\n"
        "        return False\n"
        "def f():\n"
        "    with CM() as (then, otherwise):\n"
        "        with then:\n"
        "            pass\n"
        "    return 7\n"
    )
    _source_file, seated = _seated(tmp_path, source)
    assert seated[7] is not None
    assert not isinstance(seated[7], OpaqueCitedContextManagerRefV1)
    assert not isinstance(seated[8], OpaqueCitedContextManagerRefV1)


def test_only_a_formal_enter_result_binding_qualifies():
    def head(source, line=3, col=13):
        return runtime_selected_manager_head(_unit(source), line, col)

    picked = (
        "def f(c):\n"
        "    with c.m() as (a, b):\n"
        "        with a:\n"
        "            pass\n"
    )
    assert head(picked) == "a"
    # Rebound inside the body: the head no longer holds the enter result.
    rebound = (
        "def f(c):\n"
        "    with c.m() as a:\n"
        "        with a:\n"
        "            pass\n"
        "        a = 1\n"
    )
    assert head(rebound) is None
    # The outer head is not formal-rooted (a module name is read from source).
    module_rooted = (
        "def f():\n"
        "    with g() as a:\n"
        "        with a:\n"
        "            pass\n"
    )
    assert head(module_rooted) is None
    # A nested target is not a flat name list.
    nested = (
        "def f(c):\n"
        "    with c.m() as (a, (b, d)):\n"
        "        with a:\n"
        "            pass\n"
    )
    assert head(nested) is None


def test_projection_seats_an_outer_with_as_before_its_readers(tmp_path):
    # Before #7732 the projection of this frame demanded the ``open`` row
    # before the builtin reader ran, and population stopped: nothing seated.
    source = (
        "def f(datapath, parser):\n"
        "    with open(datapath('io'), encoding='utf-8') as path:\n"
        "        reader = parser.read_csv(path)\n"
        "        with reader:\n"
        "            pass\n"
    )
    _source_file, seated = _seated(tmp_path, source)
    # ``open`` is ``builtins.open``: no artifact holds it, so it is not
    # bridged and is cited, like any callee the lifter does not have.
    assert type(seated[2]).__name__ == "OpaqueCitedContextManagerRefV1"


def test_projection_does_not_construct_an_unseated_with(tmp_path):
    # The lying twin: binding ``as`` never constructs the With.  A
    # ``with ... as`` no reader can seat still refuses when it is constructed.
    source = (
        "def f():\n"
        "    with undefined_manager() as m:\n"
        "        with m:\n"
        "            pass\n"
        "    return 7\n"
    )
    source_file, seated = _seated(tmp_path, source)
    assert not isinstance(seated[2], OpaqueCitedContextManagerRefV1)
    with_node = [n for n in source_file.nodes() if isinstance(n, With)][0]
    with pytest.raises(SourceTreePanic):
        _function_rows(source_file, with_node)


_GENERATOR_OPENS = (
    "from contextlib import contextmanager\n"
    "def f(buf):\n"
    "    with _buffer(buf) as fd:\n"
    "        fd.write('x')\n"
    "    return 7\n"
    "@contextmanager\n"
    "def _buffer(buf):\n"
    "    if isinstance(buf, str):\n"
    "        with {opener}(buf, 'w') as f:\n"
    "            yield f\n"
    "    else:\n"
    "        yield buf\n"
)


def test_generator_opening_a_file_is_constructed_from_source(tmp_path):
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    source_file, seated = _seated(tmp_path, _GENERATOR_OPENS.format(opener="open"))
    # The local ``@contextmanager`` call keeps its own frame
    # (``call_applies_own_frame``, #7757): the With is built over that frame.
    outer = next(n for n in source_file.nodes() if isinstance(n, With) and n.lineno == 3)
    assert type(outer.sugar()) is GeneratorWithSugar
    # ``open`` is ``builtins.open``: no artifact holds it, so it is not
    # bridged and is cited, like any callee the lifter does not have.
    assert type(seated[9]).__name__ == "OpaqueCitedContextManagerRefV1"


def test_generator_opening_through_an_unread_name_is_not_constructed(tmp_path):
    # The lying twin: the same body through a name that is no builtin gets no
    # citation.
    _source_file, seated = _seated(
        tmp_path, _GENERATOR_OPENS.format(opener="undefined_opener")
    )
    assert not isinstance(seated[3], OpaqueCitedContextManagerRefV1)
    assert not isinstance(seated[9], OpaqueCitedContextManagerRefV1)
