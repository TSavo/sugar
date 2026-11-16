"""Twins: a live loop's next item, and a read after the loop, see what an
item last changed, never a stale binding (#7757, steps 5 and 6).

Two gaps #8965 named, each confirmed by reading:

**A carried name whose last change in an item is a call's rebinding.**

```
def test_carry():
    token = 0

    def bump():
        nonlocal token
        token = token + 10

    seen = []
    for i in [1, 2]:
        seen.append(token)
        token = i
        bump()
    assert <claim>
```

The loop carries ``token`` (``token = i``).  ``bump()`` rebinds it after
that write (``container_mutation.havoc_after``), which binds no write key, so
the latch (``LoopRecurrenceSugar._latched``) handed item 2 the keyed write
``token = 1``.  Python's item 2 reads 11: ``seen[1] == 11`` is the truth and
``seen[1] == 1`` the lie, which could read ``sat``.  The body's threading now
reports what the one exposure rule left each name it rebound
(``_substitute_body_tracked(exposed=)``, from ``_thread_taken``); a carried
name still holding that state at the end of the item is among
``uncarried_item_changes`` (``nodes._uncarried_item_changes``), and the loop
runs as its recurrence, as #8965 runs it for a name it does not carry.

**A binding an item makes with no write key, read after the loop.**

```
def test_after():
    n = 0
    for i in [1, 2]:
        match i:
            case n:
                pass
    assert <claim>
```

``n`` is 2 after the loop.  A ``match`` capture, a nested ``def`` and an
``import`` bind no write key, so the loop did not publish them
(``live_loop_construction.loop_post_writes`` read only keyed writes): a read
after the loop read the binding from before it, and ``n == 0`` could read
``sat``.  Every name the body's threading left changed that the item bound
rather than a call rebound (``unkeyed_item_bindings``) is now published
through the loop's post-loop key; such a loop runs as its recurrence, which
binds that key to its value of the name under the guard that some item wrote
it, so the read owes.

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

_CELL = (
    "def test_carry():\n"
    "    token = 0\n"
    "\n"
    "    def bump():\n"
    "        nonlocal token\n"
    "        token = token + 10\n"
    "\n"
    "    seen = []\n"
)

# ``name: (source, truthful claim, lying claim)``.
_SHAPES = {
    "for-cell-call-rebind": (
        _CELL + "    for i in [1, 2]:\n"
        "        seen.append(token)\n"
        "        token = i\n"
        "        bump()\n"
        "    assert {claim}\n",
        "seen[1] == 11",
        "seen[1] == 1",
    ),
    "while-cell-call-rebind": (
        _CELL + "    i = 0\n"
        "    while i < 2:\n"
        "        seen.append(token)\n"
        "        i += 1\n"
        "        token = i\n"
        "        bump()\n"
        "    assert {claim}\n",
        "seen[1] == 11",
        "seen[1] == 1",
    ),
    "for-global-call-rebind": (
        "TOKEN = 0\n"
        "\n"
        "\n"
        "def bump():\n"
        "    global TOKEN\n"
        "    TOKEN = TOKEN + 10\n"
        "\n"
        "\n"
        "seen = []\n"
        "for i in [1, 2]:\n"
        "    seen.append(TOKEN)\n"
        "    TOKEN = i\n"
        "    bump()\n"
        "\n"
        "\n"
        "def test_carry():\n"
        "    assert {claim}\n",
        "seen[1] == 11",
        "seen[1] == 1",
    ),
    "for-match-capture-after": (
        "def test_after():\n"
        "    n = 0\n"
        "    for i in [1, 2]:\n"
        "        match i:\n"
        "            case n:\n"
        "                pass\n"
        "    assert {claim}\n",
        "n == 2",
        "n == 0",
    ),
    "while-match-capture-after": (
        "def test_after():\n"
        "    n = 0\n"
        "    i = 0\n"
        "    while i < 2:\n"
        "        i += 1\n"
        "        match i:\n"
        "            case n:\n"
        "                pass\n"
        "    assert {claim}\n",
        "n == 2",
        "n == 0",
    ),
    "for-def-after": (
        "def test_after():\n"
        "    def g():\n"
        "        return 0\n"
        "\n"
        "    for i in [1, 2]:\n"
        "\n"
        "        def g():\n"
        "            return 1\n"
        "\n"
        "    assert {claim}\n",
        "g() == 1",
        "g() == 0",
    ),
    "for-import-after": (
        "def test_after():\n"
        "    m = None\n"
        "    for i in [1, 2]:\n"
        "        import os as m\n"
        "    assert {claim}\n",
        "m is not None",
        "m is None",
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
def test_what_an_item_changed_is_never_read_stale(
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
