"""Twins: a ``for``, ``with`` or comprehension store target reads a
rebindable name after the code its statement ran before it.

```
TOKEN = 0
def gen():
    global TOKEN
    yield 0
    TOKEN = 1
    yield 0
def test_reset():
    d = {}
    for d[TOKEN] in gen():
        pass
    assert <claim>
```

Per item Python takes the iterator's next value (code: the generator runs
to its next ``yield``), then reads the target's receiver and key, then
stores (``__setitem__``).  The second ``next`` rebinds ``TOKEN`` before the
second store reads it, so ``d`` holds two keys, ``0`` and ``1``.  The
truthful claim is ``len(d) == 2``; the lying one, which a target read once
against the scope before the loop would give, ``len(d) == 1``.

A ``with`` runs its manager's ``__enter__`` before it reads and stores its
``as`` target: ``with m as d[TOKEN]:`` stores under the ``TOKEN``
``__enter__`` left, so ``before`` (read after ``m`` was made, before the
``with``) is not a key.  Before, the ``with`` threaded its header's calls
and not ``__enter__`` (``container_mutation._operates_header``): ``m`` is a
read and runs nothing, so the target read ``TOKEN`` as ``before`` holds it,
the one term, and ``before in d`` could fold to true and read ``sat``.  The
``with`` now takes the one header rule a ``for``, an ``if``, a ``while`` and
a ``match`` take (``thread_header(..., operated=True)``).

A comprehension's store target (``[0 for d[TOKEN] in gen()]``) is the
``for`` shape inside an expression.

#8847 and #8856 route a rebindable name read after a code-running
sub-expression through one door (``nodes._scope_after``'s ``rebinds``,
``container_mutation.rebound_after``; ``nodes._substituted_store_target_parts``,
``nodes._scope_after_store_target`` for a store target).  These shapes read
their targets by their own statements' paths: a ``for`` or comprehension
target with no name leaf is refused by name (no target pattern), a live
loop's store leaf likewise, and an unrolled loop's store leaves are read by
the same door in the state their item begins in (``For._item_unpack``).  A
lying claim is never ``sat``; a truthful one is never ``unsat``.

Each half goes through ``run_source_through_real_solver``: real ``sugar
mint`` then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

_GEN = (
    "TOKEN = 0\n"
    "\n"
    "\n"
    "def gen():\n"
    "    global TOKEN\n"
    "    yield 0\n"
    "    TOKEN = 1\n"
    "    yield 0\n"
    "\n"
    "\n"
)

_ENTER = (
    "TOKEN = 0\n"
    "\n"
    "\n"
    "class Enter:\n"
    "    def __enter__(self):\n"
    "        global TOKEN\n"
    "        TOKEN = 1\n"
    "        return 0\n"
    "\n"
    "    def __exit__(self, exc_type, exc, tb):\n"
    "        return False\n"
    "\n"
    "\n"
)

# ``name: (source, line of the test function, truthful claim, lying claim)``.
_SHAPES = {
    "for-generator": (
        _GEN + "def test_reset():\n"
        "    d = {{}}\n"
        "    for d[TOKEN] in gen():\n"
        "        pass\n"
        "    assert {claim}\n",
        11,
        "len(d) == 2",
        "len(d) == 1",
    ),
    "with-enter": (
        _ENTER + "def test_reset():\n"
        "    m = Enter()\n"
        "    before = TOKEN\n"
        "    d = {{}}\n"
        "    with m as d[TOKEN]:\n"
        "        pass\n"
        "    assert {claim}\n",
        14,
        "before not in d",
        "before in d",
    ),
    "comprehension-generator": (
        _GEN + "def test_reset():\n"
        "    d = {{}}\n"
        "    [0 for d[TOKEN] in gen()]\n"
        "    assert {claim}\n",
        11,
        "len(d) == 2",
        "len(d) == 1",
    ),
}


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_header_store_target_read_after_its_code_is_another_evaluation(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, line, truthful, lying = _SHAPES[shape]
    claim = truthful if half == "truthful" else lying
    result = run_source_through_real_solver(
        tmp_path / shape / half, source.format(claim=claim)
    )
    verdict = claim_verdict(result.prove_doc, claims_from_line=line)
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
