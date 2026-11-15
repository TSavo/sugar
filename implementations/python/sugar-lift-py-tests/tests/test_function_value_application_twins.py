"""A call through a function's value applies it as a call by name does (#7757).

A local plain ``def`` binds its name to the function its statement built
(``nodes._binds_function_value``), and ``h = g; h()`` calls that value.  The
value's one application (``LambdaCallable.callable_application_with``) does
what a call by name of the ``def`` did:

- it reads each closure cell where the call stands (``Call._closure_cells``,
  ``CallableApplication.captured``): Python reads the cell when the body
  runs, so ``y = 2`` before ``h()`` is what ``g`` returns;
- what the body does to an object the caller sees reaches the caller through
  the one projection (``container_mutation.source_helper_actual_states``,
  ``call_site_value.caller_visible_values``): a ``nonlocal`` rebinding and an
  append are read after the call.

Before, the value's application carried no cell (refused by name) and the
caller's threading followed only a call spelled by name (the cell was
unknown after the call): neither half was decided.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


_CELL_READ_AT_THE_CALL = """\
def test_cell():
    y = 1

    def g():
        return y

    h = g
    y = 2
    assert h() == {claim}
"""

_NONLOCAL_REBOUND_THROUGH_THE_VALUE = """\
def test_count():
    n = 0

    def bump():
        nonlocal n
        n += 1

    b = bump
    b()
    assert n == {claim}
"""

_APPEND_THROUGH_THE_VALUE = """\
def test_append():
    xs = []

    def add():
        xs.append(1)

    a = add
    a()
    assert len(xs) == {claim}
"""

_TWINS = {
    "cell-read-at-the-call": (_CELL_READ_AT_THE_CALL, "2", "1"),
    "nonlocal-rebound": (_NONLOCAL_REBOUND_THROUGH_THE_VALUE, "1", "0"),
    "append-carried": (_APPEND_THROUGH_THE_VALUE, "1", "0"),
}


@pytest.mark.parametrize("shape", sorted(_TWINS))
def test_a_call_through_the_value_is_decided(shape: str, tmp_path: Path) -> None:
    source, true, false = _TWINS[shape]
    truthful = run_source_through_real_solver(
        tmp_path / "t", source.format(claim=true)
    )
    lying = run_source_through_real_solver(tmp_path / "l", source.format(claim=false))
    print(
        json.dumps(
            {"truthful": truthful.verdict, "lying": lying.verdict}, sort_keys=True
        )
    )
    assert truthful.verdict == "sat", truthful.prove_doc
    assert lying.verdict == "unsat", lying.prove_doc
