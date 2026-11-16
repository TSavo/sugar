"""Twins: a module global any call may have changed is never read as it was
before that call (#7757 H7).

#9102 made a same-file call that reads a mutable module global record it, so
a later call reads the global as that call left it
(``python:after(<call result>, "global:G")``).  A global changed by anything
else -- a callee nothing here answers (a formal handed a function that
changes it), a method of an object that holds it, or a same-file call made
in one arm of an ``if`` only -- was still handed to a later call as the
caller's entry held it, so a lie could read ``sat`` and a truth ``unsat``.

Every call now names in its completed record what it may reach
(``call_site_value.bind_after_call``): a same-file call what its contract
reads, plus every module global where it is handed an object that may be or
hold one (``lambda_callable._after_labels``); any other call every module
global.  A later call reads a mutable global after the newest such record
(``call_site_sugar._global_after_call``), and a record one arm of an ``if``
made stands under that arm's guard only (``if_sugar._arm_evaluations``): the
global after the ``if`` is the join of the arms, never the entry value on the
arm that ran the call nor the call's state on the arm that did not.

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
    # (1) A callee nothing here answers: the formal ``cb`` is handed ``bump``,
    # which changes ``G``; ``h`` must not read the entry's ``[1]``.
    "unanswered-callee-then-a-call-reads-the-global": (
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
        "def f(cb):\n"
        "    cb()\n"
        "    return h()\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f(bump) == 2",
        "f(bump) == 1",
    ),
    # (1') The same, read in the caller's own frame.
    "unanswered-callee-then-the-frame-reads-the-global": (
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
        "def f(cb):\n"
        "    cb()\n"
        "    return G[0]\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f(bump) == 2",
        "f(bump) == 1",
    ),
    # (2) A same-file call in one arm of an ``if``, the arm not taken: the
    # global after the ``if`` is the entry's on that arm.
    "call-in-one-arm-not-taken": (
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
        "def f(c):\n"
        "    if c:\n"
        "        bump()\n"
        "    return h()\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f(False) == 1",
        "f(False) == 2",
    ),
    # (2') The arm taken: the global after the ``if`` is what ``bump`` left.
    "call-in-one-arm-taken": (
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
        "def f(c):\n"
        "    if c:\n"
        "        bump()\n"
        "    return h()\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f(True) == 2",
        "f(True) == 1",
    ),
    # (3) A method of an object that holds the global changes it.
    "method-of-an-object-holding-the-global": (
        "G = [1]\n"
        "\n"
        "\n"
        "class Box:\n"
        "    def __init__(self, xs):\n"
        "        self.xs = xs\n"
        "\n"
        "    def bump(self):\n"
        "        self.xs[0] = 2\n"
        "\n"
        "\n"
        "def h():\n"
        "    return G[0]\n"
        "\n"
        "\n"
        "def f():\n"
        "    b = Box(G)\n"
        "    b.bump()\n"
        "    return h()\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f() == 2",
        "f() == 1",
    ),
    # (3') A same-file function handed the global as an actual changes it
    # through its formal, though it never reads it as a global.
    "same-file-call-handed-the-global": (
        "G = [1]\n"
        "\n"
        "\n"
        "def poke(xs):\n"
        "    xs[0] = 2\n"
        "\n"
        "\n"
        "def h():\n"
        "    return G[0]\n"
        "\n"
        "\n"
        "def f(ys):\n"
        "    poke(ys)\n"
        "    return h()\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f(G) == 2",
        "f(G) == 1",
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
def test_a_global_any_call_may_change_is_never_read_as_before(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, truthful, lying = _SHAPES[shape]
    text = source.format(claim=truthful if half == "truthful" else lying)
    result = run_source_through_real_solver(tmp_path / shape / half, text)
    verdict = claim_verdict(
        result.prove_doc,
        claims_from_line=_claims_line(text),
        lift_doc=result.lift_doc,
    )
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc


def test_an_unanswered_call_records_every_global() -> None:
    """A completed call that is no same-file definition's edge carries a
    record naming every module global (``EVERY_GLOBAL_SLOT``): each global's
    ``global:<name>`` formal, never an operand's."""
    from sugar_lift_py_tests.contract_input import GLOBAL_INPUT, input_formal
    from sugar_lift_py_tests.floor.call_site_value import (
        EVERY_GLOBAL_SLOT,
        AfterCallRecordValue,
    )
    from sugar_lift_py_tests.ir import ctor

    record = AfterCallRecordValue(
        ctor("python:call_result", ()), ((EVERY_GLOBAL_SLOT, None),)
    )
    assert record.reaches_every_global()
    assert record.formal_of(("global", "G")) == input_formal(GLOBAL_INPUT, "G")
    assert not record.names(("global", "G"))
    assert record.formal_of(("arg", 0)) is None
    assert record.formal_of(("cell", "G")) is None


def test_a_same_file_call_handed_an_outside_object_reaches_every_global() -> None:
    """``_made_here_all_the_way_down``: an immutable value or a builtin
    container this frame made with current contents reaches no global; a
    formal, an arrived container or one holding either may."""
    from sugar_lift_py_tests.floor import ListValue, SymbolicValue, TermValue
    from sugar_lift_py_tests.floor.lambda_callable import (
        _made_here_all_the_way_down,
    )
    from sugar_lift_py_tests.ir import make_var

    one = TermValue(1)
    made = ListValue((one,), allocation="made")
    outside = SymbolicValue(make_var("xs"))
    assert _made_here_all_the_way_down(one)
    assert _made_here_all_the_way_down(made)
    assert not _made_here_all_the_way_down(outside)
    assert not _made_here_all_the_way_down(ListValue((outside,), allocation="made"))
    assert not _made_here_all_the_way_down(
        ListValue((one,), allocation=None, arrival="read")
    )
