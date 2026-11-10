"""A loop over a runtime list runs its body once per item, each on the last's state.

``r = [1]; r.append(2); n = 0; for x in r: n = n + x; return n`` lifted as
returning ``0``. The list is decided only when the loop reduces, so the body is
a live recurrence read through the temporal, not unrolled by substitution; an
assignment there evaluated its RHS and bound nothing (only ``n += x`` rebound
``n``), so every iteration read the pre-loop ``0``.

And an iteration body with more than one face (a call that may raise) ended
the loop: its first iteration's faces were handed back as the loop's outcome,
so later iterations -- and their halts -- were never reduced; and every
iteration's call shared one occurrence, so iteration 2's call was claimed to
complete exactly when iteration 1's did.

The law: an assignment rebinds its names to the completed value in the
temporal, as an augmented assignment always has. Each face of an iteration is
its own path: a halt leaves the loop under its guard; a completed face carries
its own state into the next iteration under its guard. Each live iteration is
its own occurrence segment, as an unrolled iteration is.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor import TermValue, TupleValue

from test_builtin_container_mutation import _only_return, _returns

PRELUDE = "    r = [1]\n    r.append(2)\n    n = 0\n"


def test_an_assignment_in_the_body_carries_to_the_next_item(tmp_path):
    source = "def f():\n" + PRELUDE + "    for x in r:\n        n = n + x\n    return n\n"
    assert _only_return(tmp_path, source) == TermValue(3)


def test_statements_in_the_body_see_each_others_stores(tmp_path):
    source = (
        "def f():\n" + PRELUDE + "    m = 0\n    for x in r:\n"
        "        n = n + x\n        m = n * 10\n    return (n, m)\n"
    )
    assert _only_return(tmp_path, source) == TupleValue((TermValue(3), TermValue(30)))


def test_an_augmented_assignment_still_carries(tmp_path):
    source = "def f():\n" + PRELUDE + "    for x in r:\n        n += x\n    return n\n"
    assert _only_return(tmp_path, source) == TermValue(3)


def test_a_chained_assignment_carries(tmp_path):
    source = (
        "def f():\n" + PRELUDE + "    k = 0\n    for x in r:\n"
        "        n = k = n + x\n    return (n, k)\n"
    )
    assert _only_return(tmp_path, source) == TupleValue((TermValue(3), TermValue(3)))


def test_a_destructuring_assignment_carries(tmp_path):
    source = (
        "def f():\n" + PRELUDE + "    k = 0\n    for x in r:\n"
        "        n, k = n + x, x\n    return (n, k)\n"
    )
    assert _only_return(tmp_path, source) == TupleValue((TermValue(3), TermValue(2)))


def _halt_occurrences(halts):
    return sorted(getattr(halt, "occurrence", "") for halt in halts)


def test_every_iteration_of_a_body_that_may_raise_runs_and_may_raise(tmp_path):
    source = (
        "import os\ndef f():\n" + PRELUDE + "    for x in r:\n"
        "        os.getpid()\n        n = n + x\n    return n\n"
    )
    returns, halts = _returns(tmp_path, source)
    assert returns == [TermValue(3)]
    occurrences = _halt_occurrences(halts)
    assert len(occurrences) == 2
    assert occurrences[0].endswith("#0") and occurrences[1].endswith("#1")


def test_a_continue_face_carries_into_the_next_item(tmp_path):
    source = (
        "import os\ndef f():\n" + PRELUDE + "    for x in r:\n"
        "        os.getpid()\n        n = n + x\n        if x == 1:\n"
        "            continue\n        break\n    return n\n"
    )
    returns, halts = _returns(tmp_path, source)
    assert returns == [TermValue(3)]
    assert len(_halt_occurrences(halts)) == 2
