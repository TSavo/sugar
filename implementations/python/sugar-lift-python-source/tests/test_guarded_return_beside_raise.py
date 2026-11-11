"""``if c: return v`` beside a ``raise`` keeps the completed return exit.

Python returns ``v`` where ``c`` holds and raises where it does not.  The
block reducer dropped the return in two places:

* the ``if`` arm returned and the ``else`` arm raised, so neither falls
  through and only the halted arm was kept;
* ``if c: return v`` was followed by a ``raise`` statement, so the halt ran
  unguarded over the prefix and the earlier return was forgotten.

Both claimed f always raised (or raised only under ``not c``, with nothing
under ``c``).  Now the return is a Completed exit under exactly the guard
where no halt holds, and the raise halts only under the fall-through guard.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted, complement_guard

from test_undetermined_raise_except_matching import _exits

_CASES = {
    "else-raise": "def f():\n    if [3] == [3]:\n        return 7\n    else:\n        raise ValueError\n",
    "tail-raise": "def f():\n    if [3] == [3]:\n        return 7\n    raise ValueError\n",
    "tail-raise-named": "def f():\n    y = [3] == [3]\n    if y:\n        return 7\n    raise ValueError\n",
}


def _returned(face):
    return [
        entry.value.value
        for entry in face.value.record.statements
        if isinstance(entry, (GuardedReturn, ReturnValue))
    ]


@pytest.mark.parametrize("case", sorted(_CASES))
def test_the_return_is_a_completed_exit_beside_the_raise(tmp_path, case):
    exits = _exits(tmp_path, _CASES[case]).exits
    (halt,) = [face for face in exits if isinstance(face, Halted)]
    (done,) = [face for face in exits if isinstance(face, Completed)]
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "ValueError"
    assert _returned(done) == [7]
    # Exactly complementary: the return holds where the raise does not.
    assert halt.guard == complement_guard(done.guard) or done.guard == complement_guard(
        halt.guard
    )


def test_an_opaque_condition_keeps_the_return_beside_both_halts(tmp_path):
    exits = _exits(
        tmp_path,
        "import os\ndef f():\n    if os.getpid() == 3:\n        return 7\n    raise ValueError\n",
    ).exits
    done = [face for face in exits if isinstance(face, Completed)]
    assert [_returned(face) for face in done] == [[7]]
    assert any(
        isinstance(face, Halted)
        and isinstance(face.effect, RaiseEffect)
        and face.effect.exception_name == "ValueError"
        for face in exits
    )
