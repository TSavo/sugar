"""A ``with`` whose manager comes from a parameter is an opaque two-faced manager.

``with monkeypatch.context() as m:`` (26 pandas test sites) and
``with self.buffer:`` (``io/common.py:1016``, under every ``get_handle``)
select ``__enter__``/``__exit__`` by the type of the object the caller
passes.  Nothing in the frame knows that type, and the With refused
(``runtime-selected``).  The manager is now opaque and keyed on the With's
site:
- evaluating the head is two-faced (``python:formal_manager.constructs``);
- ``__enter__`` and ``__exit__`` are each two-faced;
- suppression is the undecided truth of the opaque exit result.
It never refuses silently and never completes totally.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
from sugar_source_tree.formal_manager_head import formal_manager_head

from test_undetermined_raise_except_matching import _exits


def _owners(exits):
    return sorted(
        face.effect.producer_node_owner
        for face in exits
        if isinstance(face, Halted) and isinstance(face.effect, UndeterminedRaiseEffect)
    )


@pytest.mark.parametrize(
    ("source", "head"),
    [
        (
            "def f(monkeypatch):\n    with monkeypatch.context() as m:\n"
            "        raise ValueError\n    return 2\n",
            "monkeypatch.context()",
        ),
        ("def f(self):\n    with self.buffer:\n        raise ValueError\n    return 1\n",
         "self.buffer"),
    ],
)
def test_formal_manager_is_opaque_and_two_faced(tmp_path, source, head):
    exits = _exits(tmp_path, source).exits
    assert _owners(exits) == [
        f"FormalSelectedManager:{head}.__enter__",
        f"FormalSelectedManager:{head}.__exit__",
        f"FormalSelectedManager:{head}.construct",
    ]
    # The body's raise stays a face, and the undecided exit truth may
    # suppress it, so the function may also return.
    assert any(
        isinstance(face, Halted) and not isinstance(face.effect, UndeterminedRaiseEffect)
        for face in exits
    )
    completed = [face for face in exits if isinstance(face, Completed)]
    assert completed
    assert all("python:formal_manager.constructs" in repr(face.guard) for face in completed)


def test_only_a_formal_rooted_effect_free_head_qualifies():
    def head(source):
        return formal_manager_head(source, 2, 9)

    assert head("def f(p):\n    with p.a.b(1, k='x'):\n        pass\n") == "p.a.b(1, k='x')"
    # The parameter is rebound before the with: not the caller's value.
    assert head("def f(p):\n    with p.m():\n        pass\n    p = 1\n") is None
    # A non-constant argument has its own evaluation.
    assert head("def f(p, q):\n    with p.m(q()):\n        pass\n") is None
    # A module-level name is not a parameter.
    assert head("def f(p):\n    with x.m():\n        pass\n") is None
    # A subscript is not an attribute/call chain.
    assert head("def f(p):\n    with p[0]:\n        pass\n") is None
