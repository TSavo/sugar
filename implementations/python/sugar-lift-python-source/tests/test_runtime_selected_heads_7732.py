"""The ``with`` heads once refused as ``runtime-selected`` (#7732).

* A head that is the enter result of a manager a caller passed
  (``with c.builder.if_else(p) as (then, otherwise):`` then ``with then:``,
  ``core/_numba/extensions.py:362``): no frame knows the passed object's type,
  so nothing decides the manager.
* A same-module ``@contextmanager`` whose body runs ``with open(...)``
  (``io/formats/format.py:1052``): the call is its coordinate and edge
  (#7757 step 6), and the ``with`` is built over what the head reduces to.

A ``with``'s manager is what its head reduces to (#7757); nothing is seated
for it before construction.
"""

from __future__ import annotations

from sugar_source_tree.nodes import With

from test_contextlib_suppress_source_exit_faces import _corpus, _open


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
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        WithReducedManagerSugar,
    )

    source_file = _open(_corpus(tmp_path, _GENERATOR_OPENS.format(opener="open")))
    # The local ``@contextmanager`` call is its coordinate and edge (#7757
    # step 6): the With is built over the value the head reduces to.  Verdict
    # moved: it was built over the generator's frame (``GeneratorWithSugar``).
    outer = next(n for n in source_file.nodes() if isinstance(n, With) and n.lineno == 3)
    assert type(outer.sugar()) is WithReducedManagerSugar
