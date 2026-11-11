"""A class call carries its constructor's halts (#7756).

``Cls(x)`` is a call.  Its constructor frame applies through the one
application routine (``CallSiteValue.producer_outcome``), so a halt of the
initializer -- including one from a method the initializer calls -- is a halt
of the call, never packed inside a completed value.

Solver twins (red until the solver door gives verdicts, #7766): the truthful
source's claim holds (``sat``); the lying source makes the constructor raise,
so the assertion after the class call is never reached (``unsat``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _pair(tmp_path: Path, name: str, truthful: str, lying: str) -> None:
    t = run_source_through_real_solver(tmp_path / f"{name}-truthful", truthful)
    lie = run_source_through_real_solver(tmp_path / f"{name}-lying", lying)
    print(json.dumps({"truthful": t.verdict, "lying": lie.verdict}, sort_keys=True))
    assert t.verdict == "sat"
    assert lie.verdict == "unsat"


_CONSTRUCTOR = """\
class Box:
    def __init__(self, n):
        self.n = n
        self.state = self.check(n)

    def check(self, n):
{body}


def test_box():
    box = Box({actual})
    assert box.n == {actual}
"""

_ALWAYS = "        raise ValueError('bad box')"
_PLAIN = "        return n"
_ONE_FACE = "        if n > 5:\n            raise ValueError('too big')\n        return n"


def test_constructor_halt_reaches_the_class_call(tmp_path: Path) -> None:
    """``Box(3)``: the initializer's ``self.check`` completes vs always raises."""

    _pair(
        tmp_path,
        "constructor-always",
        _CONSTRUCTOR.format(body=_PLAIN, actual=3),
        _CONSTRUCTOR.format(body=_ALWAYS, actual=3),
    )


def test_constructor_halt_on_one_face_reaches_the_class_call(tmp_path: Path) -> None:
    """``Box(n)`` raising for ``n > 5``: the actual selects the face."""

    _pair(
        tmp_path,
        "constructor-one-face",
        _CONSTRUCTOR.format(body=_ONE_FACE, actual=3),
        _CONSTRUCTOR.format(body=_ONE_FACE, actual=9),
    )


# ---------------------------------------------------------------------------
# The same sources in process (a unit check, not a twin).  Before #7756 the
# raising constructors gave a completed ``ReceiverStatePartitionValue`` and the
# ``box.n`` read refused on it.
# ---------------------------------------------------------------------------


def _test_function_outcome(source: str):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree.nodes import FunctionDef
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name.startswith("test_")
    )
    return function_universe_outcome(function)


@pytest.mark.parametrize(
    ("body", "actual", "raises"),
    [
        (_PLAIN, 3, False),
        (_ALWAYS, 3, True),
        (_ONE_FACE, 3, False),
        (_ONE_FACE, 9, True),
    ],
    ids=["plain", "always-raises", "one-face-not-taken", "one-face-taken"],
)
def test_constructor_halt_in_process(body: str, actual: int, raises: bool) -> None:
    from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted

    outcome = _test_function_outcome(_CONSTRUCTOR.format(body=body, actual=actual))
    if not raises:
        assert isinstance(outcome, Complete), outcome
        return
    assert isinstance(outcome, ExitSet), outcome
    assert [type(face) for face in outcome.exits] == [Halted]
    assert outcome.exits[0].effect.exception_name == "ValueError"
