"""A class call carries its constructor's halts to its caller at prove
(#7756, #7757 step 6).

``Cls(x)`` is a call: its coordinate and an edge to the class's join symbol
(``python:<module>.<Class>``), joined at prove to the class's constructor
contract (``tree_enumerate.class_universe_outcome``) as a call of a ``def``
is (the owner's ruling of 2026-11-15, "Edge, join at prove").  The reduction
never applies the constructor's body: a class call is the two faces of the
one unanswered call, and a halt of the initializer -- including one from a
method the initializer calls, itself an edge joined in turn -- reaches the
caller through the join (#8690).

Solver twins: the lying source makes the constructor raise, so the assertion
after the class call is never reached (``unsat``: a certain halt in a callee
refutes the lie).  Where the raise is in a method ``__init__`` calls on
``self`` (``self.check(n)``), that call is not dispatched until #7757 step 8,
so the lie reads ``open`` until then (``_LIE_OPEN_UNTIL_STEP_8``).  The
truthful source's claim reads ``box.n``, a field of a call's result: the read names the instance as its construction left it
(``python:after(<call result>, "out")``), and the class's contract states
that field's value and that a read of it completes (#7757 step 7), so the
join decides it at prove: ``sat``.  Between step 6 and step 7 it was
``open``; before step 6 it was decided ``sat`` at the reduction by following
``Box.__init__``'s body.  The whole source may still owe members of the
methods' own proofs (``self.check(n)`` in ``__init__``'s own row), so the
truthful half is read on the test function's claims
(``witness_harness.claim_verdict``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)


def _pair(
    tmp_path: Path, name: str, truthful: str, lying: str, *, lie: str = "unsat"
) -> None:
    t = run_source_through_real_solver(tmp_path / f"{name}-truthful", truthful)
    lie_result = run_source_through_real_solver(tmp_path / f"{name}-lying", lying)
    print(
        json.dumps(
            {"truthful": t.verdict, "lying": lie_result.verdict}, sort_keys=True
        )
    )
    # The test function is the one ``def test_`` line; every method above it.
    (test_line,) = (
        number
        for number, line in enumerate(truthful.splitlines(), start=1)
        if line.startswith("def test_")
    )
    assert t.verdict != "unsat"
    assert claim_verdict(t.prove_doc, claims_from_line=test_line) == "sat"
    assert lie_result.verdict == lie


# The constructor's halt below comes from ``self.check(n)``: a method call on
# ``self``, which arrived by binding, so its dispatch is not decided and it
# is the unanswered call (#8738).  ``__init__``'s contract states that halt as
# the undetermined raise under the call's own completes atom, which nothing at
# the class call decides, so the lie reads ``open`` on main (scorecard
# 43738710481), listed on #7661.  Dispatch of ``self.m()`` at prove (#7757
# step 8: #8750 prove side, the lift side not merged) joins ``check``'s halt
# and decides the lie ``unsat``.  Never ``sat`` for the lie.
_LIE_OPEN_UNTIL_STEP_8 = "open"


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
        lie=_LIE_OPEN_UNTIL_STEP_8,
    )


def test_constructor_halt_on_one_face_reaches_the_class_call(tmp_path: Path) -> None:
    """``Box(n)`` raising for ``n > 5``: the actual selects the face."""

    _pair(
        tmp_path,
        "constructor-one-face",
        _CONSTRUCTOR.format(body=_ONE_FACE, actual=3),
        _CONSTRUCTOR.format(body=_ONE_FACE, actual=9),
        lie=_LIE_OPEN_UNTIL_STEP_8,
    )


_FIELD = """\
class Box:
    def __init__(self, n):
        self.n = n


def test_box():
    assert Box({actual}).n == 3
"""


def test_field_of_a_class_call_result_is_joined_at_prove(tmp_path: Path) -> None:
    """``Box(3).n``: the class's contract states the field the construction
    set and that its read completes (#7757 step 7)."""
    t = run_source_through_real_solver(
        tmp_path / "field-truthful", _FIELD.format(actual=3)
    )
    lie = run_source_through_real_solver(tmp_path / "field-lying", _FIELD.format(actual=4))
    print(json.dumps({"truthful": t.verdict, "lying": lie.verdict}, sort_keys=True))
    # ``__init__``'s own row stores on a formal with no actual and may owe
    # it: the truthful half is read on the test function's claims.
    test_line = _FIELD.splitlines().index("def test_box():") + 1
    assert t.verdict != "unsat"
    assert claim_verdict(t.prove_doc, claims_from_line=test_line) == "sat"
    assert lie.verdict == "unsat"


_CHANGED = """\
class Box:
    def __init__(self, n):
        self.n = n


def poke(b):
    b.n = 9


def test_box():
    box = Box(3)
{change}
    assert box.n == {expected}
"""


@pytest.mark.parametrize(
    "change",
    ["    poke(box)", "    box.n = 9", "    del box.n\n    box.n = 9"],
    ids=["handed-to-a-call", "stored", "deleted-then-stored"],
)
def test_a_changed_instance_is_not_its_constructed_state(
    tmp_path: Path, change: str
) -> None:
    """After code may have changed the instance -- a call it is handed to, a
    store or a delete on it -- the caller holds another value, never the
    state the class's contract states (#7757 step 7): the lie that reads the
    constructed field is never ``sat``, and nothing decides the truth here
    (what ``poke`` leaves in ``b`` is not stated yet)."""
    t = run_source_through_real_solver(
        tmp_path / "changed-truthful", _CHANGED.format(change=change, expected=9)
    )
    lie = run_source_through_real_solver(
        tmp_path / "changed-lying", _CHANGED.format(change=change, expected=3)
    )
    print(json.dumps({"truthful": t.verdict, "lying": lie.verdict}, sort_keys=True))
    assert t.verdict != "unsat"
    assert lie.verdict != "sat"


# ---------------------------------------------------------------------------
# The same sources in process (a unit check, not a twin).  The class call is
# the edge's two faces whatever the constructor does: its halt is decided at
# prove, never at the reduction.
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


def _decided_raises(outcome) -> list:
    """The exception names of the halted faces the reduction decided (every
    halt but the one unanswered call's undetermined raise)."""
    from sugar_lift_py_tests.outcome import Halted

    return [
        getattr(face.effect, "exception_name", None)
        for face in getattr(outcome, "exits", ())
        if isinstance(face, Halted)
        and type(face.effect).__name__ != "UndeterminedRaiseEffect"
    ]


@pytest.mark.parametrize(
    ("body", "actual"),
    [(_PLAIN, 3), (_ALWAYS, 3), (_ONE_FACE, 3), (_ONE_FACE, 9)],
    ids=["plain", "always-raises", "one-face-not-taken", "one-face-taken"],
)
def test_constructor_halt_is_decided_at_prove(body: str, actual: int) -> None:
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    outcome = _test_function_outcome(_CONSTRUCTOR.format(body=body, actual=actual))
    assert isinstance(outcome, ExitSet), outcome
    kinds = {type(face) for face in outcome.exits}
    # The edge's two faces: it may complete, it may halt.
    assert Completed in kinds and Halted in kinds, outcome
    assert "ValueError" not in _decided_raises(outcome), outcome


_FACTORY = """\
class Box:
    def __init__(self, n):
        self.n = n
        if n > 5:
            raise ValueError('too big')

    @classmethod
    def make(cls, n):
        return cls(n)
"""


@pytest.mark.parametrize("actual", [3, 9])
def test_class_method_call_is_its_edge(actual: int) -> None:
    """``Box.make(n)``: the classmethod the lookup selected on the class is
    its coordinate and edge (#7757 step 6), whatever ``make``'s body does;
    ``__init__``'s raise reaches the caller at prove (unit check)."""
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.outcome import ExitSet, Halted
    from sugar_source_tree.nodes import ClassDef
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (_FACTORY, "factory.py", blake3_512_of(_FACTORY.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (class_def,) = tuple(node for node in tree.nodes() if isinstance(node, ClassDef))
    ctx = ReduceContext.root(owner="test")
    box = class_def.sugar().desugar(ctx).completed_value()
    outcome = box.call_method_value(
        "make", (TermValue(actual),), owner="test", blame="make-site", ctx=ctx
    )
    assert isinstance(outcome, ExitSet), outcome
    halts = [face for face in outcome.exits if isinstance(face, Halted)]
    assert [type(face.effect).__name__ for face in halts] == ["UndeterminedRaiseEffect"]
