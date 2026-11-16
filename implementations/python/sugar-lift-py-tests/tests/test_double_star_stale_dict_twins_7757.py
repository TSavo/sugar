"""Twins: ``C(**d)`` never binds ``d``'s entries when its contents are not
current (#7757 H2).

``SourceCallFrame.bind_actuals`` had its own ``**`` reader: it bound a
``**d`` operand from ``d.entries`` for any ``DictValue``, current or not,
for a class, a function value or a bound method applied from
``SpreadCallSugar._finish``.  The ``{**d}`` display's reader
(``_spread_dict_pairs``) and every other dict read ask whether ``d``'s
contents are current (``object_identity.contents_current``).  A dict that
arrived -- a module global, a field, a callee's return -- or one a call
may have changed holds entries this frame does not see the change of, so
the binder put an old value into the callee's contract: a claim on the old
value could read ``sat``, and the true one ``unsat``.

The call now expands ``**d`` through the one reader
(``spread_sugar._call_keywords``).  Where it gives no keyword roster the
call is the one unanswered call (``UnknownCalleeCallV1``), two-faced and
owed: undecided, never bound from stale entries.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each
half goes through ``run_source_through_real_solver``: real ``sugar mint``
then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

# ``name: (source, truthful claim, lying claim)``.  Braces are doubled: the
# source is a ``str.format`` template.
_SHAPES = {
    # A module global arrives by binding; ``bump`` changed it before the
    # spread.  The old entry is ``x == 1``; Python binds ``x == 2``.
    "global-dict-changed-before-spread": (
        '_D = {{"x": 1}}\n'
        "\n"
        "\n"
        "class C:\n"
        "    def __init__(self, x):\n"
        "        self.x = x\n"
        "\n"
        "\n"
        "def bump():\n"
        '    _D["x"] = 2\n'
        "\n"
        "\n"
        "def f():\n"
        "    bump()\n"
        "    return C(**_D).x\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f() == 2",
        "f() == 1",
    ),
    # A dict this frame made, then handed to a call that changes it: the
    # entries the frame made are not its contents after the call.
    "local-dict-changed-by-callee": (
        "class C:\n"
        "    def __init__(self, x):\n"
        "        self.x = x\n"
        "\n"
        "\n"
        "def g(d):\n"
        '    d["x"] = 2\n'
        "\n"
        "\n"
        "def f():\n"
        '    d = {{"x": 1}}\n'
        "    g(d)\n"
        "    return C(**d).x\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f() == 2",
        "f() == 1",
    ),
    # A dict this frame made and nothing changed: still bound by name.
    "current-dict-binds": (
        "class C:\n"
        "    def __init__(self, x):\n"
        "        self.x = x\n"
        "\n"
        "\n"
        "def f():\n"
        '    d = {{"x": 1}}\n'
        "    return C(**d).x\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f() == 1",
        "f() == 2",
    ),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows the helpers."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_double_star_spread_never_refutes_a_truth_nor_admits_a_lie(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, truthful, lying = _SHAPES[shape]
    text = source.format(claim=truthful if half == "truthful" else lying)
    result = run_source_through_real_solver(tmp_path / shape / half, text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
