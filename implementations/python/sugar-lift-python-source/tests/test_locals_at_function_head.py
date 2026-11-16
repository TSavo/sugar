"""``locals()`` at the head of a module-level function is a dict of its formals.

In a function, ``locals()`` returns a snapshot dict of the frame's bound locals,
in ``co_varnames`` order: positional parameters, then keyword-only
parameters, then ``*args``, then ``**kwargs``.  A module-level function has
no free variables.  So before any other local is bound, the snapshot is exactly
``{name: value}`` over the parameters.  numpy's ``_make_options_dict`` opens
with ``{k: v for k, v in list(locals().items()) if v is not None}``, which
was two-faced (``UnknownCallee:items`` and ``BuiltinDunderCall:list``).
Once another local is bound, a nested frame calls it, or ``locals`` is rebound,
the call stays an ordinary call.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
from sugar_lift_py_tests.outcome.exit_set import Halted

from test_undetermined_raise_except_matching import _exits


def _returns(tmp_path, source):
    exits = _exits(tmp_path, source).exits
    return sorted(
        entry.value.value
        for face in exits
        if not isinstance(face, Halted)
        for entry in face.value.record.statements
        if isinstance(entry, GuardedReturn)
    ), [face.effect.producer_node_owner for face in exits if isinstance(face, Halted)]


# The options-dict idiom and the ``co_varnames`` order were read through
# ``f``'s call of ``g``, reducing ``g``'s body at lift.  A same-file call is
# its coordinate and edge, joined at prove (#7757 step 6), so ``f`` holds
# ``g(3)``'s keyed result and every read of it is undecided; those two tests
# are deleted.  The snapshot's shape (formals in ``co_varnames`` order) is
# read off the tree by ``locals_snapshot_shape`` below.


def test_after_another_local_is_bound_the_call_stays_ordinary(tmp_path):
    _, halts = _returns(
        tmp_path,
        "def g(p=None):\n    x = 1\n    return locals()\n"
        "def f():\n    o = g(3)\n    if 'x' in o:\n        return 7\n    return 8\n",
    )
    assert halts


def _unit(source: str):
    """The typed unit of ``source``: the snapshot reader walks its tree."""
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.tree import SourceFile

    return SourceFile(
        (source, "locals_head.py", blake3_512_of(source.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    ).unit


def test_a_rebound_locals_is_not_the_builtin():
    from sugar_source_tree.locals_snapshot import locals_snapshot_shape

    source = "def locals():\n    return {}\ndef g(p):\n    return locals()\n"
    assert locals_snapshot_shape(_unit(source), 4, 11) is None
    nested = "def g(p):\n    return (lambda: locals())()\n"
    assert locals_snapshot_shape(_unit(nested), 2, 20) is None
    plain = "def g(p, *, q):\n    return locals()\n"
    assert locals_snapshot_shape(_unit(plain), 2, 11).parameters == ("p", "q")
    ordered = "def g(a, *r, k=2, **kw):\n    return locals()\n"
    assert locals_snapshot_shape(_unit(ordered), 2, 11).parameters == (
        "a",
        "k",
        "r",
        "kw",
    )
