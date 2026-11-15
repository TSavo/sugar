"""A generator function's call at a With head is its edge, never its body.

``with g():`` where ``g`` is a same-file generator function -- undecorated, or
under ``@contextmanager`` -- evaluates the call, which is ``g``'s coordinate
and edge, joined at prove (#7757 step 6, the owner's ruling of 2026-11-15).
What the call returns (a generator object, a ``_GeneratorContextManager``) is
what ``g``'s contract states; nothing here decides it.  So the With enters an
undecided manager (``WithReducedManagerSugar``): ``__enter__`` and ``__exit__``
are each two-faced and owed, and no ``TypeError`` is decided at lift.

Verdicts moved: before, an undecorated generator head was decided to raise the
interpreter's ``TypeError`` (``GeneratorObjectWithSugar``), and a
``@contextmanager`` head ran the generator to its first yield
(``GeneratorWithSugar``), so ``f`` was decided to return 7.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
    WithReducedManagerSugar,
)

from test_contextmanager_generator_protocol import (
    _SUPPRESSES_VALUE_ERROR,
    _function_rows,
    _imported,
)

_UNDECORATED = "def cm():\n    try:\n        yield 1\n    except ValueError:\n        pass\n"


@pytest.mark.parametrize("contextlib_enrolled", (True, False))
@pytest.mark.parametrize(
    "body", ("pass", "raise ValueError('v')", "return 8"), ids=("pass", "raise", "return")
)
def test_an_undecorated_generator_head_is_the_undecided_manager(
    tmp_path, contextlib_enrolled, body
):
    opened = _imported(
        tmp_path, _UNDECORATED, body, contextlib_enrolled=contextlib_enrolled
    )
    sugar, rows = _function_rows(*opened)
    assert sugar is WithReducedManagerSugar
    # Nothing decides the call's result: no TypeError is decided, and the
    # call and the manager steps are owed.
    assert ("halt", "TypeError") not in rows
    assert ("halt", None) in rows


def test_a_contextmanager_generator_head_is_the_undecided_manager(tmp_path):
    opened = _imported(
        tmp_path,
        _SUPPRESSES_VALUE_ERROR,
        "raise ValueError('v')",
        contextlib_enrolled=False,
    )
    sugar, rows = _function_rows(*opened)
    assert sugar is WithReducedManagerSugar
    assert ("halt", None) in rows
