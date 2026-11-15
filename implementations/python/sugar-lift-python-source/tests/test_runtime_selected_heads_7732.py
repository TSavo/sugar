"""The ``with`` heads once refused as ``runtime-selected`` (#7732).

* A head that is the enter result of a manager a caller passed
  (``with c.builder.if_else(p) as (then, otherwise):`` then ``with then:``,
  ``core/_numba/extensions.py:362``): no frame knows the passed object's type,
  so nothing decides the manager.
* A same-module ``@contextmanager`` whose body runs ``with open(...)``
  (``io/formats/format.py:1052``): the call keeps its own frame, and the
  ``with`` is built over it.

A ``with``'s manager is what its head reduces to (#7757); nothing is seated
for it before construction.
"""

from __future__ import annotations

from sugar_source_tree.formal_manager_head import runtime_selected_manager_head
from sugar_source_tree.nodes import With

from test_cited_unreadable_manager import _unit
from test_contextlib_suppress_source_exit_faces import _corpus, _open


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

    source_file = _open(_corpus(tmp_path, _GENERATOR_OPENS.format(opener="open")))
    # The local ``@contextmanager`` call keeps its own frame
    # (``call_applies_own_frame``, #7757): the With is built over that frame.
    outer = next(n for n in source_file.nodes() if isinstance(n, With) and n.lineno == 3)
    assert type(outer.sugar()) is GeneratorWithSugar
