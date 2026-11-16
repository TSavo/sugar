"""Twins: a deferred operation on a formal inside a live loop's item is its
own evaluation per item, never one term for all of them (#7757, step 6).

An operation whose operand is a formal once waited for the caller's actual
on a deferred carrier, discharged at the function's end, outside every live
item, so every item's ``c + 0`` was one term.  Python evaluates
``c.__add__(0)`` once per item, and a ``__add__`` that counts returns 1,
then 2: the truth ``r[0] != r[1]`` could read ``unsat``.  The carrier is
deleted (#7757 NEW-1): every operation on a formal is evaluated where it
stands, keyed under the live item it runs in.

A method call on a formal mints no carrier (#7757 NEW-1): it is the
dispatched edge where the formal's class is an input, else the one
unanswered call (``UnknownCalleeCallV1``).  Both state their result as
``python:call_result(<call term>, python:occurrence(<site>, <path>...))``,
their completes atom over that result, and their halt at
``occurrence_key(site)``, each read where the call evaluates: inside a live
item, that item's path.  So each item's ``c.bump()`` is its own term.

An operation that mints no carrier on a formal -- an attribute read, the
one undecided read -- keys its value term, its completes atom and its halt
per evaluation where it evaluates (``occurrence_key(site)`` under the live
item's path), as ``undecided_binary_terms`` does: each item's read of
``c.count`` is its own ``python:attribute_result("count", c, <key>)``.

A subscript read on a formal (``c[0]``, ``c[0:]``) is no carrier any more
(#7757, audit 2 row NEW-1): it is the undecided read, whose value is keyed
per evaluation, ``python:subscript_result(<receiver>, <index>, <key>)``, the
key ``occurrence_key(site)`` taken where the read evaluates -- inside a live
item, that item's path.  A ``__getitem__`` that counts returns 1, then 2, and
the two items' reads are two terms, so the truth ``r[0] != r[1]`` is never
``unsat`` and the lie ``r[0] == r[1]`` never ``sat``.

A binary operator on a formal (``c + 0``) no longer defers at all: it is the
undecided two faces where it runs (``undecided_binary_faces``, #7757 audit
row NEW-1), keyed under the live item it runs in, so the ``binary-per-item``
twin now reads that law.

``-c`` / ``+c`` / ``~c``, ``iter(c)`` and ``next(c)`` on a formal mint no
carrier any more (#7757 NEW-1): each is the undecided read evaluated where
it stands, its value ``python:unary_result("<op>", c, <key>)`` /
``python:iter_result(c, <key>)`` / ``python:next_result(c, <key>)``
(``floor_value.undecided_result_terms``), ``<key>`` the occurrence key
inside the live item, so each item's operation is still its own
(``test_each_item_evaluates_its_own_deferred_operation``).

A comparison (``c == 0``) and a truth test (``not c``) on a formal are the
undecided two faces, and their value is keyed per evaluation too (#7757
NEW-1, option (b)): ``python:compare_result("Eq", c, 0, <key>)`` and
``python:truth_result(c, <key>)`` (``floor_value.undecided_predicate_result``),
the key their completes atom and their halt already carry.  A counting
``__eq__`` or ``__bool__`` answers differently each time, so two evaluations
-- in two live items, or twice in one body -- are two atoms, and the truth
``r[0] != r[1]`` is never ``unsat`` (``compare-per-item``,
``compare-twice``, ``truth-per-item``).

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

_COUNTER = (
    "class Counter:\n"
    "    def __init__(self):\n"
    "        self.k = 0\n"
    "\n"
    "    def __add__(self, other):\n"
    "        self.k += 1\n"
    "        return self.k\n"
    "\n"
    "    def __getitem__(self, index):\n"
    "        self.k += 1\n"
    "        return self.k\n"
    "\n"
    "    def bump(self):\n"
    "        self.k += 1\n"
    "        return self.k\n"
    "\n"
    "\n"
)

_COUNTING_READER = (
    "class Reader:\n"
    "    def __init__(self):\n"
    "        self.k = 0\n"
    "\n"
    "    @property\n"
    "    def count(self):\n"
    "        self.k += 1\n"
    "        return self.k\n"
    "\n"
    "    def __getattr__(self, name):\n"
    "        self.k += 1\n"
    "        return self.k\n"
    "\n"
    "\n"
)

_COUNTING_EQ = (
    "class Equaler:\n"
    "    def __init__(self):\n"
    "        self.k = 0\n"
    "\n"
    "    def __eq__(self, other):\n"
    "        self.k += 1\n"
    "        return self.k == 1\n"
    "\n"
    "\n"
)

# ``name: (source, truthful claim, lying claim)``.
_SHAPES = {
    "binary-per-item": (
        _COUNTER + "def twice(c):\n"
        "    out = []\n"
        "    for _ in (1, 2):\n"
        "        out.append(c + 0)\n"
        "    return out\n"
        "\n"
        "\n"
        "def test_twice():\n"
        "    r = twice(Counter())\n"
        "    assert {claim}\n",
        "r[0] != r[1]",
        "r[0] == r[1]",
    ),
    "subscript-per-item": (
        _COUNTER + "def twice(c):\n"
        "    out = []\n"
        "    for _ in (1, 2):\n"
        "        out.append(c[0])\n"
        "    return out\n"
        "\n"
        "\n"
        "def test_twice():\n"
        "    r = twice(Counter())\n"
        "    assert {claim}\n",
        "r[0] != r[1]",
        "r[0] == r[1]",
    ),
    # ``c[0:]`` on the formal ``c``: the counting ``__getitem__`` takes the
    # slice, each item's read its own evaluation (#7757, audit 2 row NEW-1).
    "slice-per-item": (
        _COUNTER + "def twice(c):\n"
        "    out = []\n"
        "    for _ in (1, 2):\n"
        "        out.append(c[0:])\n"
        "    return out\n"
        "\n"
        "\n"
        "def test_twice():\n"
        "    r = twice(Counter())\n"
        "    assert {claim}\n",
        "r[0] != r[1]",
        "r[0] == r[1]",
    ),
    # ``c`` is read bare (``d = c``), so its class is no input of
    # ``twice``'s contract: each item's ``c.bump()`` is the unanswered call.
    "method-call-per-item": (
        _COUNTER + "def twice(c):\n"
        "    d = c\n"
        "    out = []\n"
        "    for _ in (1, 2):\n"
        "        out.append(c.bump())\n"
        "    return out\n"
        "\n"
        "\n"
        "def test_twice():\n"
        "    r = twice(Counter())\n"
        "    assert {claim}\n",
        "r[0] != r[1]",
        "r[0] == r[1]",
    ),
    # ``c`` is read only as a receiver: its class is ``twice``'s input, so
    # each item's ``c.bump()`` is the dispatched edge.
    "dispatched-method-call-per-item": (
        _COUNTER + "def twice(c):\n"
        "    out = []\n"
        "    for _ in (1, 2):\n"
        "        out.append(c.bump())\n"
        "    return out\n"
        "\n"
        "\n"
        "def test_twice():\n"
        "    r = twice(Counter())\n"
        "    assert {claim}\n",
        "r[0] != r[1]",
        "r[0] == r[1]",
    ),
    # An attribute read on a parameter mints no carrier: it is the one
    # undecided read, keyed per evaluation where it evaluates
    # (``floor_value.undecided_attribute_result``:
    # ``python:attribute_result("<name>", c, <key>)``), so each item's read
    # is its own term.  A property that counts, and a ``__getattr__`` that
    # counts, return 1, then 2.
    "attribute-property-per-item": (
        _COUNTING_READER + "def twice(c):\n"
        "    out = []\n"
        "    for _ in (1, 2):\n"
        "        out.append(c.count)\n"
        "    return out\n"
        "\n"
        "\n"
        "def test_twice():\n"
        "    r = twice(Reader())\n"
        "    assert {claim}\n",
        "r[0] != r[1]",
        "r[0] == r[1]",
    ),
    "attribute-getattr-per-item": (
        _COUNTING_READER + "def twice(c):\n"
        "    out = []\n"
        "    for _ in (1, 2):\n"
        "        out.append(c.missing)\n"
        "    return out\n"
        "\n"
        "\n"
        "def test_twice():\n"
        "    r = twice(Reader())\n"
        "    assert {claim}\n",
        "r[0] != r[1]",
        "r[0] == r[1]",
    ),
    # An operation on a formal that is the undecided read itself, keyed per
    # evaluation (#7757 NEW-1): a counting ``__neg__``, and ``next`` over one
    # iterator.
    "unary-per-item": (
        "class Negator:\n"
        "    def __init__(self):\n"
        "        self.k = 0\n"
        "\n"
        "    def __neg__(self):\n"
        "        self.k += 1\n"
        "        return self.k\n"
        "\n"
        "\n"
        "def twice(c):\n"
        "    out = []\n"
        "    for _ in (1, 2):\n"
        "        out.append(-c)\n"
        "    return out\n"
        "\n"
        "\n"
        "def test_twice():\n"
        "    r = twice(Negator())\n"
        "    assert {claim}\n",
        "r[0] != r[1]",
        "r[0] == r[1]",
    ),
    "next-per-item": (
        "def twice(c):\n"
        "    out = []\n"
        "    for _ in (1, 2):\n"
        "        out.append(next(c))\n"
        "    return out\n"
        "\n"
        "\n"
        "def test_twice():\n"
        "    r = twice(iter([1, 2]))\n"
        "    assert {claim}\n",
        "r[0] != r[1]",
        "r[0] == r[1]",
    ),
    # A comparison on a formal is the undecided ``==``, its value keyed per
    # evaluation (#7757 NEW-1, option (b)): a counting ``__eq__`` answers
    # True, then False.
    "compare-per-item": (
        _COUNTING_EQ + "def twice(c):\n"
        "    out = []\n"
        "    for _ in (1, 2):\n"
        "        out.append(c == 0)\n"
        "    return out\n"
        "\n"
        "\n"
        "def test_twice():\n"
        "    r = twice(Equaler())\n"
        "    assert {claim}\n",
        "r[0] != r[1]",
        "r[0] == r[1]",
    ),
    # ``(p == q) != (p == q)``: the same comparison twice in one body, two
    # sites, two evaluations of the counting ``__eq__``.
    "compare-twice": (
        _COUNTING_EQ + "def both(p, q):\n"
        "    return [p == q, p == q]\n"
        "\n"
        "\n"
        "def test_twice():\n"
        "    r = both(Equaler(), 0)\n"
        "    assert {claim}\n",
        "r[0] != r[1]",
        "r[0] == r[1]",
    ),
    # A truth test on a formal is the one truth rule's two faces, its value
    # keyed per evaluation: a counting ``__bool__`` answers True, then False.
    "truth-per-item": (
        "class Truther:\n"
        "    def __init__(self):\n"
        "        self.k = 0\n"
        "\n"
        "    def __bool__(self):\n"
        "        self.k += 1\n"
        "        return self.k == 1\n"
        "\n"
        "\n"
        "def twice(c):\n"
        "    out = []\n"
        "    for _ in (1, 2):\n"
        "        out.append(not c)\n"
        "    return out\n"
        "\n"
        "\n"
        "def test_twice():\n"
        "    r = twice(Truther())\n"
        "    assert {claim}\n",
        "r[0] != r[1]",
        "r[0] == r[1]",
    ),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows every helper."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_each_item_evaluates_its_own_deferred_operation(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, truthful, lying = _SHAPES[shape]
    claim = truthful if half == "truthful" else lying
    text = source.format(claim=claim)
    result = run_source_through_real_solver(tmp_path / shape / half, text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc

