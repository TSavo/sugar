"""Twins: a read after a ``with`` sees what the manager's ``__exit__`` may
have rebound, on every face.

```
TOKEN = None
class Exit:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        global TOKEN
        TOKEN = []
        return False
def bump():
    global TOKEN
    TOKEN = []
def test_reset():
    with Exit():
        bump()
        inside = TOKEN
    assert <claim>
```

Python runs ``__exit__`` after the body: ``inside`` is the list ``bump()``
made and ``TOKEN`` the one ``__exit__`` made, so the truthful claim is
``inside is not TOKEN`` and the lying one ``inside is TOKEN``.

Before, the ``with`` published what its body left (``With._published``) and
the block's header thread (``__enter__``, ``thread_header``) moved a name
after it only where the body had not rebound it: ``TOKEN`` after the
``with`` was the body's value, the term ``inside`` holds, and the lie could
fold to true and read ``sat`` (#8865's listed limit).  ``__exit__`` is now an
operation on the manager after the body (``container_mutation.thread_exit``,
the one exposure rule, keyed by the ``with``'s own evaluation): every name
it may rebind is another evaluation after the ``with`` -- the body
completed, a halt the manager suppresses (``Swallow``) -- and unknown at a
halt that propagates through it to an enclosing handler.

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

_PREFIX = (
    "TOKEN = None\n"
    "\n"
    "\n"
    "class Exit:\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "\n"
    "    def __exit__(self, exc_type, exc, tb):\n"
    "        global TOKEN\n"
    "        TOKEN = []\n"
    "        return False\n"
    "\n"
    "\n"
    "class Swallow:\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "\n"
    "    def __exit__(self, exc_type, exc, tb):\n"
    "        global TOKEN\n"
    "        TOKEN = []\n"
    "        return True\n"
    "\n"
    "\n"
    "def bump():\n"
    "    global TOKEN\n"
    "    TOKEN = []\n"
    "\n"
    "\n"
    "def test_reset():\n"
)
# The prefix ends on ``def test_reset():``, its last line.
_TEST_RESET_LINE = _PREFIX.count("\n")

# ``name: (body of test_reset, truthful claim, lying claim)``.
_SHAPES = {
    "exit-after-an-empty-body": (
        "    before = TOKEN\n"
        "    with Exit():\n"
        "        pass\n"
        "    assert {claim}\n",
        "before is not TOKEN",
        "before is TOKEN",
    ),
    "exit-after-a-body-rebinding": (
        "    with Exit():\n"
        "        bump()\n"
        "        inside = TOKEN\n"
        "    assert {claim}\n",
        "inside is not TOKEN",
        "inside is TOKEN",
    ),
    "exit-suppressing-a-halt": (
        "    inside = None\n"
        "    with Swallow():\n"
        "        bump()\n"
        "        inside = TOKEN\n"
        "        raise ValueError\n"
        "    assert {claim}\n",
        "inside is not TOKEN",
        "inside is TOKEN",
    ),
    "exit-under-a-propagating-halt": (
        "    inside = None\n"
        "    try:\n"
        "        with Exit():\n"
        "            bump()\n"
        "            inside = TOKEN\n"
        "            raise ValueError\n"
        "    except ValueError:\n"
        "        pass\n"
        "    assert {claim}\n",
        "inside is not TOKEN",
        "inside is TOKEN",
    ),
}


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_name_exit_may_rebind_is_another_evaluation_after_the_with(
    tmp_path: Path, shape: str, half: str
) -> None:
    body, truthful, lying = _SHAPES[shape]
    claim = truthful if half == "truthful" else lying
    result = run_source_through_real_solver(
        tmp_path / shape / half, _PREFIX + body.format(claim=claim)
    )
    verdict = claim_verdict(result.prove_doc, claims_from_line=_TEST_RESET_LINE)
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
