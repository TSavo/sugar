"""``_is_true`` / ``_is_false`` agree with content equality on every guard.

They read the guard's shape instead of comparing against a freshly built
``and_([])`` / ``not_(and_([]))`` (which authenticated the whole guard DAG's
content identity per call; #7664).  The verdict must be the one ``==`` gives.
"""

from __future__ import annotations

from sugar_lift_py_tests.ir import _Connective, and_, atomic, make_var, not_, or_
from sugar_lift_py_tests.outcome.exit_set import (
    _is_false,
    _is_true,
    false_guard,
    true_guard,
)


def _guards():
    p = atomic("py.truthy", [make_var("x")])
    q = atomic("py.truthy", [make_var("y")])
    empty_and = _Connective("and", ())
    return [
        true_guard(),
        false_guard(),
        empty_and,
        _Connective("not", (empty_and,)),
        _Connective("not", (_Connective("and", ()),)),
        _Connective("or", ()),
        _Connective("not", (_Connective("or", ()),)),
        _Connective("not", (empty_and, empty_and)),
        _Connective("not", (_Connective("not", (empty_and,)),)),
        p,
        not_(p),
        and_([p, q]),
        or_([p, q]),
        _Connective("and", (empty_and,)),
    ]


def test_shape_verdicts_equal_content_equality():
    for guard in _guards():
        assert _is_true(guard) == (guard == true_guard()), guard
        assert _is_false(guard) == (guard == false_guard()), guard
