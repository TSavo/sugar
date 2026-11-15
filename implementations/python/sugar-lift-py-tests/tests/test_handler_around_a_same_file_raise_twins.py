"""A handler around a same-file raise is decided at prove (#7757 step 7).

A call of a same-file function is its coordinate and edge, joined at prove
(the owner's ruling of 2026-11-15, "Edge, join at prove"): the reduction
never follows the callee's body, so when the call halts, the exception it
raised is ``python:raised(<call term>, <occurrence>)``
(``UnknownCalleeCallV1.faces``), whose class nothing at the reduction
decides.  The callee's contract states each halt with its raised class and
its guard (a panic locus); prove types the exception under each halt's guard
bound to the call's actuals (``consistency::with_raised_types``), so the
handler that takes it is decided there.

The twins read the second handler: the lie claims ``except Exception`` took
an exception the first handler, ``except ValueError``, already takes.  Where
no halt the callee states holds under the actual, the call completes (the
completion fact, ``completes <-> and(not g_i)``), so no handler runs at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)

_HANDLERS = """\
def boom(x):
{body}


def test_handler():
    r = 0
    try:
        boom({actual})
    except ValueError:
        r = 1
    except Exception:
        r = 2
    assert r == {claim}
"""

_ALWAYS = "    raise ValueError('boom')"
_ONE_FACE = "    if x > 0:\n        raise ValueError('positive')\n    return x"


@pytest.mark.parametrize(
    ("body", "actual"),
    [(_ALWAYS, 1), (_ONE_FACE, 1)],
    ids=["always-raises", "raises-on-this-actual"],
)
def test_the_handler_that_takes_a_same_file_raise_is_decided_at_prove(
    tmp_path: Path, body: str, actual: int
) -> None:
    truthful_source = _HANDLERS.format(body=body, actual=actual, claim=1)
    truthful = run_source_through_real_solver(tmp_path / "t", truthful_source)
    lying = run_source_through_real_solver(
        tmp_path / "l", _HANDLERS.format(body=body, actual=actual, claim=2)
    )
    print(json.dumps({"truthful": truthful.verdict, "lying": lying.verdict}))
    test_line = truthful_source.splitlines().index("def test_handler():") + 1
    # ``boom``'s own row may owe its operation on a formal (``x > 0``): the
    # truthful half is read on the test function's claims.
    assert truthful.verdict != "unsat"
    assert claim_verdict(truthful.prove_doc, claims_from_line=test_line) == "sat"
    assert lying.verdict == "unsat"


_NEVER = "    return x"


@pytest.mark.parametrize(
    ("body", "actual"),
    [(_NEVER, 1), (_ONE_FACE, -1)],
    ids=["never-raises", "raises-not-on-this-actual"],
)
def test_a_joined_call_no_halt_of_which_holds_completes(
    tmp_path: Path, body: str, actual: int
) -> None:
    """The completion fact (step 9): the callee's contract states every halt
    of its one reduction with its guard, so where none holds under the call's
    actual the call completes.  No handler runs: the lie claims the second
    handler took an exception the call never raised; the truth is the
    completed path (``r == 0``)."""
    truthful_source = _HANDLERS.format(body=body, actual=actual, claim=0)
    truthful = run_source_through_real_solver(tmp_path / "t", truthful_source)
    lying = run_source_through_real_solver(
        tmp_path / "l", _HANDLERS.format(body=body, actual=actual, claim=2)
    )
    print(json.dumps({"truthful": truthful.verdict, "lying": lying.verdict}))
    test_line = truthful_source.splitlines().index("def test_handler():") + 1
    assert claim_verdict(truthful.prove_doc, claims_from_line=test_line) == "sat"
    assert claim_verdict(lying.prove_doc, claims_from_line=test_line) == "unsat"
