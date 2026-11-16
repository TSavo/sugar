"""A ``with`` whose head is the phi of an ``if``'s managers is the reduced
manager, one way (#7757 new 7, step 6).

``with m:`` after ``if c: m = A() else: m = B()`` reads ``m`` through the
phi ``A() if <slot> else B()``.  It was split into an ``if`` over one
``with`` per arm (``With._selected_manager_sugar``) keyed on the ``if``'s
untied branch slot, beside the reduced-manager path every other head takes.
Now the head is reduced as any ternary is (``IfExpSugar._join_on``: the
``if``'s own reading selects the arm) and each arm's manager is entered and
exited on its own face (``with_source_resource_sugar._project_manager_
receiver``), so ``__enter__``/``__exit__`` are each arm's own dispatched
calls, and every face (normal exit, suppressed, propagated) is kept.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_SOURCE = """\
class Suppresses:
    def __enter__(self):
        return self

    def __exit__(self, effect_type, effect, traceback):
        return True


class Propagates:
    def __enter__(self):
        return self

    def __exit__(self, effect_type, effect, traceback):
        return False


def f(x):
    if x is None:
        m = Suppresses()
    else:
        m = Propagates()
    with m:
        raise ValueError
    return 1


def test_f():
    assert {claim}
"""


def test_the_truthful_half_is_never_refuted(tmp_path: Path) -> None:
    # ``Suppresses.__exit__`` returns True: the body's ValueError is
    # suppressed and ``f`` returns 1 after the ``with``.
    result = run_source_through_real_solver(
        tmp_path / "t", _SOURCE.format(claim="f(None) == 1")
    )
    assert result.verdict != "unsat"


@pytest.mark.parametrize(
    "claim",
    [
        # ``Propagates.__exit__`` returns False: the ValueError leaves
        # ``f``, which never returns.
        "f(0) == 1",
        # The suppressed arm returns 1, never anything else.
        "f(None) == 2",
    ],
)
def test_the_lying_half_is_never_sat(claim: str, tmp_path: Path) -> None:
    result = run_source_through_real_solver(tmp_path / "l", _SOURCE.format(claim=claim))
    assert result.verdict != "sat"
