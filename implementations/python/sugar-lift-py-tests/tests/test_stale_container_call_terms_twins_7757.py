"""Twins: a call never carries a container by contents that are not current
(#7757 H7).

Every call and edge term built its operands with ``to_term``, and a
``list``/``dict``/``set`` whose contents are not current
(``object_identity.contents_current``: it arrived by binding, or a call it
was handed may have changed it) projects the contents it arrived with.
Prove reads a display handed to a callee's formal as its contents, so
``xs = [1]; g(xs); return h(xs)`` (``h`` returning ``x[0]``) joined ``h``'s
contract on ``x := array(1)``: the claim on the old contents could read
``sat``, and the true one ``unsat``.

Every operand a call or edge carries (an actual, a keyword actual, a
default, a captured cell, a module global, a callee, a receiver, a spread
display's operand) is now named by ``object_identity.identity_term``, the
one term every undecided read already names its operand by: a stale
container by its identity, a current one by its display.  A default is the
object its ``def`` made, which every call shares, so it is named by its
identity at each call.

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
    # A list this frame made, handed to a callee nothing here resolves (a
    # formal): its contents are not current after the call, and the call of
    # ``h`` that reads it carried the old ``array(1)``.
    "list-changed-by-unknown-callee-read-by-a-call": (
        "def h(x):\n"
        "    return x[0]\n"
        "\n"
        "\n"
        "def bump(xs):\n"
        "    xs[0] = 2\n"
        "\n"
        "\n"
        "def f(g):\n"
        "    xs = [1]\n"
        "    g(xs)\n"
        "    return h(xs)\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f(bump) == 2",
        "f(bump) == 1",
    ),
    # The same-file shape: ``g`` changes the list, ``h`` reads it.
    "list-changed-by-same-file-callee-read-by-a-call": (
        "def g(xs):\n"
        "    xs[0] = 2\n"
        "\n"
        "\n"
        "def h(x):\n"
        "    return x[0]\n"
        "\n"
        "\n"
        "def f():\n"
        "    xs = [1]\n"
        "    g(xs)\n"
        "    return h(xs)\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f() == 2",
        "f() == 1",
    ),
    # A dict handed to an unknown callee, then a keyword actual of a call.
    "dict-changed-by-unknown-callee-as-a-keyword-actual": (
        "def h(*, m):\n"
        '    return m["x"]\n'
        "\n"
        "\n"
        "def bump(d):\n"
        '    d["x"] = 2\n'
        "\n"
        "\n"
        "def f(g):\n"
        '    d = {{"x": 1}}\n'
        "    g(d)\n"
        "    return h(m=d)\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f(bump) == 2",
        "f(bump) == 1",
    ),
    # ``{{**d}}`` after the call: the display's operand was ``d``'s old
    # entries, which prove read as the new dict's.
    "dict-spread-after-unknown-callee": (
        "def bump(d):\n"
        '    d["x"] = 2\n'
        "\n"
        "\n"
        "def f(g):\n"
        '    d = {{"x": 1}}\n'
        "    g(d)\n"
        "    e = {{**d}}\n"
        '    return e["x"]\n'
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f(bump) == 2",
        "f(bump) == 1",
    ),
    # A module global list a call changed while the module runs: the next
    # call's ``py.global`` carried the old ``array(1)``.
    "global-list-changed-at-module-run-then-read-by-a-call": (
        "G = [1]\n"
        "\n"
        "\n"
        "def bump():\n"
        "    G[0] = 2\n"
        "\n"
        "\n"
        "def h():\n"
        "    return G[0]\n"
        "\n"
        "\n"
        "bump()\n"
        "R = h()\n"
        "\n"
        "\n"
        "def test_r():\n"
        "    assert {claim}\n",
        "R == 2",
        "R == 1",
    ),
    # The same global changed and read from a function's own contract.
    "global-list-changed-in-a-function-then-read-by-a-call": (
        "G = [1]\n"
        "\n"
        "\n"
        "def bump():\n"
        "    G[0] = 2\n"
        "\n"
        "\n"
        "def h():\n"
        "    return G[0]\n"
        "\n"
        "\n"
        "def f():\n"
        "    bump()\n"
        "    return h()\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f() == 2",
        "f() == 1",
    ),
    # A mutable default is one object every call shares: the second call
    # finds what the first left in it, never the ``def``'s empty list.
    "mutable-default-shared-across-calls": (
        "def f(xs=[]):\n"
        "    xs.append(1)\n"
        "    return len(xs)\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    f()\n"
        "    assert {claim}\n",
        "f() == 2",
        "f() == 1",
    ),
    # A list this frame made and nothing changed: still carried by its
    # contents (the precision a current container keeps).
    "current-list-still-carries-its-contents": (
        "def h(x):\n"
        "    return x[0]\n"
        "\n"
        "\n"
        "def f():\n"
        "    xs = [1]\n"
        "    return h(xs)\n"
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
def test_a_call_never_carries_stale_contents(
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


def test_a_stale_container_refuses_its_projection_by_name() -> None:
    """A projection that reaches a stale container's ``to_term`` is a site
    that did not name it by ``identity_term``: it refuses by name, never
    states the old contents (``object_identity.refuse_stale_projection``)."""
    from sugar_lift_py_tests.floor import DictValue, ListValue, SetValue, TermValue
    from sugar_source_tree.panic import SugarNotWritten

    one = TermValue(1)
    stale = (
        ListValue((one,), allocation=None, arrival="read"),
        DictValue(((one, one),), allocation=None, arrival="read"),
        SetValue((one,), allocation=None, arrival="read"),
    )
    for value in stale:
        with pytest.raises(SugarNotWritten):
            value.to_term(owner="test")
    current = (
        ListValue((one,), allocation="made"),
        DictValue(((one, one),), allocation="made"),
        SetValue((one,), allocation="made"),
    )
    for value in current:
        value.to_term(owner="test")


def test_a_call_names_a_stale_actual_by_its_identity() -> None:
    """``call_operand_terms`` names a stale actual
    ``python:object_read(...)`` and a current one by its display."""
    from sugar_lift_py_tests.floor import ListValue, TermValue
    from sugar_lift_py_tests.floor.object_identity import call_operand_terms

    one = TermValue(1)
    stale = ListValue((one,), allocation=None, arrival="read")
    current = ListValue((one,), allocation="made")
    site = "bafkreistalecallsite"
    stale_term, current_term = call_operand_terms(
        (stale, current), (), site, owner="test"
    )
    assert stale_term.name == "python:object_read", stale_term
    assert current_term.name == "array", current_term
